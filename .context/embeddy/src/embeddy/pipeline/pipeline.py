# src/embeddy/pipeline/pipeline.py
"""Async pipeline orchestrating ingest -> chunk -> embed -> store.

The :class:`Pipeline` composes the :class:`~embeddy.ingest.Ingestor`,
chunking layer, :class:`~embeddy.embedding.Embedder`, and
:class:`~embeddy.store.VectorStore` into a single high-level interface
for ingesting documents end-to-end.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from pathlib import Path
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from embeddy.chunking import get_chunker
from embeddy.config import ChunkConfig
from embeddy.exceptions import IngestError
from embeddy.ingest import Ingestor
from embeddy.models import (
    ContentType,
    IngestError as IngestErrorModel,
    IngestStats,
)

if TYPE_CHECKING:
    from embeddy.embedding import Embedder
    from embeddy.store import VectorStore

logger = logging.getLogger(__name__)


class Pipeline:
    """Async-native pipeline orchestrating ingest -> chunk -> embed -> store.

    Args:
        embedder: The embedding model facade.
        store: The vector store.
        collection: Target collection name (created if missing).
        chunk_config: Optional chunking configuration override.
        on_file_indexed: Optional callback invoked after each successful
            ingest/reindex with ``(source_path, stats)``.  May be sync or async.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        collection: str = "default",
        chunk_config: ChunkConfig | None = None,
        on_file_indexed: Callable[[str | None, IngestStats], Any] | None = None,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._collection = collection
        self._chunk_config = chunk_config or ChunkConfig()
        self._ingestor = Ingestor()
        self._on_file_indexed = on_file_indexed

    # ------------------------------------------------------------------
    # Ensure collection exists
    # ------------------------------------------------------------------

    async def _ensure_collection(self) -> None:
        """Create the target collection if it doesn't already exist."""
        existing = await self._store.get_collection(self._collection)
        if existing is None:
            await self._store.create_collection(
                name=self._collection,
                dimension=self._embedder.dimension,
                model_name=self._embedder.model_name,
            )

    async def _fire_hook(self, source: str | None, stats: IngestStats) -> None:
        """Invoke *on_file_indexed* if set, handling sync and async callables."""
        if self._on_file_indexed is None:
            return
        result = self._on_file_indexed(source, stats)
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            await result

    # ------------------------------------------------------------------
    # ingest_text
    # ------------------------------------------------------------------

    async def ingest_text(
        self,
        text: str,
        content_type: ContentType | None = None,
        source: str | None = None,
    ) -> IngestStats:
        """Ingest raw text through the full pipeline.

        Args:
            text: The text content to ingest.
            content_type: Explicit content type (defaults to GENERIC).
            source: Optional source identifier.

        Returns:
            :class:`IngestStats` with processing metrics.
        """
        start = time.monotonic()
        stats = IngestStats()

        try:
            await self._ensure_collection()
            ingest_result = await self._ingestor.ingest_text(
                text,
                content_type=content_type,
                source=source,
            )
        except Exception as exc:
            stats.errors.append(
                IngestErrorModel(
                    file_path=source,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            )
            stats.elapsed_seconds = time.monotonic() - start
            return stats

        stats = await self._process_ingest_result(ingest_result, stats)
        stats.files_processed = 1
        stats.collection = self._collection
        stats.elapsed_seconds = time.monotonic() - start
        if not stats.errors:
            await self._fire_hook(source, stats)
        return stats

    # ------------------------------------------------------------------
    # ingest_file
    # ------------------------------------------------------------------

    async def ingest_file(
        self,
        path: str | Path,
        content_type: ContentType | None = None,
    ) -> IngestStats:
        """Ingest a file through the full pipeline.

        Supports content-hash deduplication: if the file's content hash
        already exists in the collection, the file is skipped.

        Args:
            path: Path to the file.
            content_type: Override auto-detected content type.

        Returns:
            :class:`IngestStats` with processing metrics.
        """
        start = time.monotonic()
        stats = IngestStats()
        path = Path(path)

        try:
            await self._ensure_collection()
            ingest_result = await self._ingestor.ingest_file(path, content_type=content_type)
        except Exception as exc:
            stats.errors.append(
                IngestErrorModel(
                    file_path=str(path),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            )
            stats.elapsed_seconds = time.monotonic() - start
            return stats

        # Content-hash dedup: skip if already ingested
        content_hash = ingest_result.source.content_hash
        if content_hash:
            try:
                already_exists = await self._store.has_content_hash(
                    self._collection,
                    content_hash,
                )
                if already_exists:
                    stats.chunks_skipped = 1
                    stats.elapsed_seconds = time.monotonic() - start
                    return stats
            except Exception:
                # If dedup check fails, proceed with ingestion anyway
                logger.warning("Content hash check failed, proceeding with ingestion", exc_info=True)

        stats = await self._process_ingest_result(ingest_result, stats)
        stats.files_processed = 1
        stats.collection = self._collection
        stats.content_hash = ingest_result.source.content_hash
        stats.elapsed_seconds = time.monotonic() - start
        if not stats.errors:
            await self._fire_hook(str(path), stats)
        return stats

    # ------------------------------------------------------------------
    # ingest_directory
    # ------------------------------------------------------------------

    async def ingest_directory(
        self,
        path: str | Path,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        recursive: bool = True,
    ) -> IngestStats:
        """Ingest all matching files in a directory.

        Args:
            path: Directory path.
            include: Glob patterns to include (e.g. ``["*.py", "*.md"]``).
                If None, all files are included.
            exclude: Glob patterns to exclude (e.g. ``["*.pyc"]``).
            recursive: Whether to recurse into subdirectories.

        Returns:
            :class:`IngestStats` with aggregate metrics.
        """
        start = time.monotonic()
        stats = IngestStats()
        path = Path(path)

        if not path.exists() or not path.is_dir():
            stats.errors.append(
                IngestErrorModel(
                    file_path=str(path),
                    error=f"Directory not found or not a directory: {path}",
                    error_type="IngestError",
                )
            )
            stats.elapsed_seconds = time.monotonic() - start
            return stats

        # Collect files
        files = self._collect_files(path, include=include, exclude=exclude, recursive=recursive)

        # Process each file
        for file_path in files:
            file_stats = await self.ingest_file(file_path)
            stats.files_processed += file_stats.files_processed
            stats.chunks_created += file_stats.chunks_created
            stats.chunks_embedded += file_stats.chunks_embedded
            stats.chunks_stored += file_stats.chunks_stored
            stats.chunks_skipped += file_stats.chunks_skipped
            stats.errors.extend(file_stats.errors)

        stats.elapsed_seconds = time.monotonic() - start
        return stats

    # ------------------------------------------------------------------
    # reindex_file
    # ------------------------------------------------------------------

    async def reindex_file(self, path: str | Path) -> IngestStats:
        """Delete existing chunks for a file, then re-ingest it.

        Args:
            path: Path to the file.

        Returns:
            :class:`IngestStats` with processing metrics.
        """
        start = time.monotonic()
        stats = IngestStats()
        path = Path(path)

        if not path.exists():
            stats.errors.append(
                IngestErrorModel(
                    file_path=str(path),
                    error=f"File not found: {path}",
                    error_type="IngestError",
                )
            )
            stats.elapsed_seconds = time.monotonic() - start
            return stats

        try:
            await self._ensure_collection()
            chunks_removed = await self._store.delete_by_source(self._collection, str(path))
        except Exception as exc:
            stats.errors.append(
                IngestErrorModel(
                    file_path=str(path),
                    error=f"Failed to delete old chunks: {exc}",
                    error_type=type(exc).__name__,
                )
            )
            stats.elapsed_seconds = time.monotonic() - start
            return stats

        # Re-ingest (bypass dedup — we just deleted the old content)
        try:
            ingest_result = await self._ingestor.ingest_file(path)
        except Exception as exc:
            stats.errors.append(
                IngestErrorModel(
                    file_path=str(path),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            )
            stats.elapsed_seconds = time.monotonic() - start
            return stats

        stats = await self._process_ingest_result(ingest_result, stats)
        stats.files_processed = 1
        stats.chunks_removed = chunks_removed
        stats.collection = self._collection
        stats.content_hash = ingest_result.source.content_hash
        stats.elapsed_seconds = time.monotonic() - start
        if not stats.errors:
            await self._fire_hook(str(path), stats)
        return stats

    # ------------------------------------------------------------------
    # delete_source
    # ------------------------------------------------------------------

    async def delete_source(self, source_path: str) -> int:
        """Delete all chunks from a given source path.

        Args:
            source_path: The source path to delete.

        Returns:
            Number of chunks deleted.
        """
        return await self._store.delete_by_source(self._collection, source_path)

    # ------------------------------------------------------------------
    # Internal: process a single IngestResult
    # ------------------------------------------------------------------

    async def _process_ingest_result(
        self,
        ingest_result: Any,
        stats: IngestStats,
    ) -> IngestStats:
        """Chunk, embed, and store a single IngestResult.

        Updates ``stats`` in-place and returns it.
        """
        # Chunk
        chunker = get_chunker(ingest_result.content_type, self._chunk_config)
        chunks = chunker.chunk(ingest_result)

        if not chunks:
            return stats

        stats.chunks_created += len(chunks)

        # Embed
        try:
            embeddings = await self._embedder.encode(
                [c.content for c in chunks],
            )
            stats.chunks_embedded += len(embeddings)
        except Exception as exc:
            source_path = ingest_result.source.file_path
            stats.errors.append(
                IngestErrorModel(
                    file_path=source_path,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            )
            return stats

        # Store
        try:
            await self._store.add(self._collection, chunks, embeddings)
            stats.chunks_stored += len(chunks)
        except Exception as exc:
            source_path = ingest_result.source.file_path
            stats.errors.append(
                IngestErrorModel(
                    file_path=source_path,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            )

        return stats

    # ------------------------------------------------------------------
    # Internal: collect files from a directory
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_files(
        directory: Path,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        recursive: bool = True,
    ) -> list[Path]:
        """Collect file paths from a directory matching include/exclude patterns.

        Args:
            directory: Base directory.
            include: Glob patterns to include (default: all files).
            exclude: Glob patterns to exclude.
            recursive: Whether to recurse into subdirectories.

        Returns:
            Sorted list of file paths.
        """
        if recursive:
            all_files = sorted(p for p in directory.rglob("*") if p.is_file())
        else:
            all_files = sorted(p for p in directory.iterdir() if p.is_file())

        if include:
            all_files = [f for f in all_files if any(fnmatch.fnmatch(f.name, pat) for pat in include)]

        if exclude:
            all_files = [f for f in all_files if not any(fnmatch.fnmatch(f.name, pat) for pat in exclude)]

        return all_files
