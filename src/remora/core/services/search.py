"""Semantic search service boundary and optional embeddy-backed implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from remora.core.model.config import SearchConfig

logger = logging.getLogger(__name__)


@runtime_checkable
class SearchServiceProtocol(Protocol):
    @property
    def available(self) -> bool: ...

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]: ...

    async def find_similar(
        self,
        chunk_id: str,
        collection: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]: ...

    async def index_file(self, path: str, collection: str | None = None) -> None: ...

    async def delete_source(self, path: str, collection: str | None = None) -> None: ...


class SearchService:
    """Async semantic search service backed by embeddy."""

    def __init__(self, config: SearchConfig, project_root: Path) -> None:
        self._config = config
        self._project_root = project_root
        self._client: Any = None
        self._pipeline: Any = None
        self._search_svc: Any = None
        self._store: Any = None
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def initialize(self) -> None:
        if not self._config.enabled:
            logger.info("Search service disabled by configuration")
            return

        if self._config.mode == "remote":
            client_cls = self._load_remote_client_class()
            if client_cls is None:
                logger.warning(
                    "Search enabled but embeddy is not installed. "
                    "Install with: uv sync --extra search"
                )
                return

            self._client = client_cls(
                base_url=self._config.embeddy_url,
                timeout=self._config.timeout,
            )
            try:
                await self._client.health()
                self._available = True
                logger.info("Search service connected to %s", self._config.embeddy_url)
            # Error boundary: remote embeddy outages should degrade search without crashing startup.
            except (OSError, TimeoutError):
                logger.warning(
                    "Embeddy server not reachable at %s; search unavailable",
                    self._config.embeddy_url,
                )
                self._available = False
            return

        await self._initialize_local()

    def _load_remote_client_class(self) -> Any | None:
        """Lazily import embeddy remote client class."""
        try:
            from embeddy.client import EmbeddyClient
        except ImportError:
            return None
        return EmbeddyClient

    async def _initialize_local(self) -> None:
        """Initialize local in-process embeddy components."""
        try:
            from embeddy import Embedder, Pipeline, VectorStore
            from embeddy.config import ChunkConfig, EmbedderConfig, StoreConfig
            from embeddy.search import SearchService as EmbeddySearchService
        except ImportError:
            logger.warning(
                "Search local mode requires full embeddy installation. "
                "Install with: uv sync --extra search-local"
            )
            return

        db_path = self._project_root / self._config.db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_config = EmbedderConfig(
            mode="local",
            model_name=self._config.model_name,
            embedding_dimension=self._config.embedding_dimension,
        )
        store_config = StoreConfig(db_path=str(db_path))
        chunk_config = ChunkConfig(strategy="auto")

        embedder = Embedder(embedder_config)
        self._store = VectorStore(store_config)
        await self._store.initialize()

        self._pipeline = Pipeline(
            embedder=embedder,
            store=self._store,
            collection=self._config.default_collection,
            chunk_config=chunk_config,
        )
        self._search_svc = EmbeddySearchService(embedder, self._store)
        self._available = True
        logger.info("Search service initialized in local mode (model: %s)", self._config.model_name)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._store is not None:
            await self._store.close()

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []

        target = collection or self._config.default_collection
        if self._client is not None:
            result = await self._client.search(query, target, top_k=top_k, mode=mode)
            return result.get("results", [])

        if self._search_svc is not None:
            from embeddy.models import SearchMode

            mode_enum = SearchMode(mode)
            results = await self._search_svc.search(query, target, top_k=top_k, mode=mode_enum)
            return [
                {
                    "chunk_id": item.chunk_id,
                    "content": item.content,
                    "score": item.score,
                    "source_path": item.source_path,
                    "content_type": item.content_type,
                    "chunk_type": item.chunk_type,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "name": item.name,
                    "metadata": item.metadata,
                }
                for item in results.results
            ]

        return []

    async def find_similar(
        self,
        chunk_id: str,
        collection: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []

        target = collection or self._config.default_collection
        if self._client is not None:
            result = await self._client.find_similar(chunk_id, target, top_k=top_k)
            return result.get("results", [])

        if self._search_svc is not None:
            results = await self._search_svc.find_similar(chunk_id, target, top_k=top_k)
            return [
                {
                    "chunk_id": item.chunk_id,
                    "content": item.content,
                    "score": item.score,
                    "source_path": item.source_path,
                    "content_type": item.content_type,
                    "chunk_type": item.chunk_type,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "name": item.name,
                    "metadata": item.metadata,
                }
                for item in results.results
            ]

        return []

    async def index_file(self, path: str, collection: str | None = None) -> None:
        if not self._available:
            return

        target = collection or self.collection_for_file(path)
        if self._client is not None:
            await self._client.reindex(path, target)
            return

        if self._pipeline is not None:
            await self._pipeline.reindex_file(path)

    async def delete_source(self, path: str, collection: str | None = None) -> None:
        if not self._available:
            return

        target = collection or self.collection_for_file(path)
        if self._client is not None:
            await self._client.delete_source(path, target)
            return

        if self._pipeline is not None:
            await self._pipeline.delete_source(path)

    async def index_directory(
        self,
        path: str,
        collection: str | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self._available:
            return {"error": "search service not available"}

        target = collection or self._config.default_collection
        if self._client is not None:
            return await self._client.ingest_directory(
                path,
                target,
                include=include,
                exclude=exclude,
            )

        if self._pipeline is not None:
            stats = await self._pipeline.ingest_directory(path, include=include, exclude=exclude)
            return {
                "files_processed": stats.files_processed,
                "chunks_created": stats.chunks_created,
                "chunks_embedded": stats.chunks_embedded,
                "chunks_stored": stats.chunks_stored,
                "chunks_skipped": stats.chunks_skipped,
                "errors": [
                    {"file_path": error.file_path, "error": error.error} for error in stats.errors
                ],
                "elapsed_seconds": stats.elapsed_seconds,
            }

        return {"error": "no backend available"}

    def collection_for_file(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        return self._config.collection_map.get(ext, self._config.default_collection)


__all__ = ["SearchService", "SearchServiceProtocol"]
