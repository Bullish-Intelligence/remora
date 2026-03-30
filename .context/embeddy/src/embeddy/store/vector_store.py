# src/embeddy/store/vector_store.py
"""Async-native vector store wrapping sqlite-vec + FTS5.

SQLite operations are synchronous but run in ``asyncio.to_thread()`` to
avoid blocking the async event loop. A single connection with WAL mode
supports concurrent reads; writes are serialized by SQLite's internal
locking (fine for single-process use).

Schema:
    - ``collections`` — namespace table (id, name, dimension, model_name, distance_metric, created_at, metadata)
    - ``chunks`` — chunk metadata (id, collection_id, content, content_type, chunk_type, source_path, start_line, end_line, name, parent, metadata, content_hash, created_at)
    - ``vec_chunks_{collection_id}`` — per-collection sqlite-vec virtual table
    - ``fts_chunks_{collection_id}`` — per-collection FTS5 virtual table
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import struct
import uuid
from datetime import datetime
from typing import Any

import sqlite_vec

from embeddy.config import StoreConfig
from embeddy.exceptions import StoreError
from embeddy.models import (
    Chunk,
    Collection,
    CollectionStats,
    ContentType,
    DistanceMetric,
    Embedding,
    SearchFilters,
)


def _serialize_float32_vec(vec: list[float]) -> bytes:
    """Pack a list of floats into raw little-endian float32 bytes for sqlite-vec."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _sanitize_collection_id(collection_id: str) -> str:
    """Return a safe identifier for use in SQL table names.

    Replaces hyphens with underscores and strips non-alphanumeric chars.
    """
    return "".join(c if c.isalnum() or c == "_" else "_" for c in collection_id)


class VectorStore:
    """Async-native vector store wrapping sqlite-vec + FTS5.

    All public methods are ``async`` and run SQLite operations in a thread
    pool via :func:`asyncio.to_thread`.

    Args:
        config: Store configuration (``db_path``, ``wal_mode``).
    """

    def __init__(self, config: StoreConfig) -> None:
        self._config = config
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open the database, load extensions, enable WAL mode, create base tables.

        Safe to call multiple times (idempotent).
        """
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        if self._conn is None:
            # check_same_thread=False is required because asyncio.to_thread()
            # may dispatch calls to different threads in the pool. We serialize
            # writes ourselves via SQLite's internal locking + WAL mode.
            self._conn = sqlite3.connect(self._config.db_path, check_same_thread=False)
            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)

        # WAL mode only works for file-based databases, not :memory:
        if self._config.wal_mode and self._config.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")

        self._conn.execute("PRAGMA foreign_keys=ON")

        # Base tables
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS collections (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                dimension INTEGER NOT NULL,
                model_name TEXT NOT NULL,
                distance_metric TEXT NOT NULL DEFAULT 'cosine',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                collection_id TEXT NOT NULL REFERENCES collections(id),
                content TEXT NOT NULL,
                content_type TEXT NOT NULL,
                chunk_type TEXT,
                source_path TEXT,
                start_line INTEGER,
                end_line INTEGER,
                name TEXT,
                parent TEXT,
                metadata TEXT,
                content_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_collection ON chunks(collection_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(collection_id, source_path);
            CREATE INDEX IF NOT EXISTS idx_chunks_content_hash ON chunks(content_hash);
            CREATE INDEX IF NOT EXISTS idx_chunks_content_type ON chunks(collection_id, content_type);
            """
        )
        self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    async def _get_journal_mode(self) -> str:
        """Return the current SQLite journal mode (for test verification)."""
        return await asyncio.to_thread(self._get_journal_mode_sync)

    def _get_journal_mode_sync(self) -> str:
        assert self._conn is not None
        row = self._conn.execute("PRAGMA journal_mode").fetchone()
        return row[0] if row else ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise StoreError("VectorStore is not initialized. Call initialize() first.")
        return self._conn

    def _resolve_collection_sync(self, name: str) -> tuple[str, int]:
        """Look up a collection by name. Returns (id, dimension). Raises StoreError if not found."""
        conn = self._require_conn()
        row = conn.execute("SELECT id, dimension FROM collections WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise StoreError(f"Collection '{name}' does not exist")
        return row[0], row[1]

    def _vec_table(self, collection_id: str) -> str:
        return f"vec_chunks_{_sanitize_collection_id(collection_id)}"

    def _fts_table(self, collection_id: str) -> str:
        return f"fts_chunks_{_sanitize_collection_id(collection_id)}"

    # ------------------------------------------------------------------
    # Collection CRUD
    # ------------------------------------------------------------------

    async def create_collection(
        self,
        name: str,
        dimension: int,
        model_name: str,
        distance_metric: DistanceMetric = DistanceMetric.COSINE,
    ) -> Collection:
        """Create a new collection with per-collection vec and FTS virtual tables."""
        return await asyncio.to_thread(self._create_collection_sync, name, dimension, model_name, distance_metric)

    def _create_collection_sync(
        self,
        name: str,
        dimension: int,
        model_name: str,
        distance_metric: DistanceMetric,
    ) -> Collection:
        conn = self._require_conn()
        collection_id = str(uuid.uuid4())
        safe_id = _sanitize_collection_id(collection_id)

        try:
            conn.execute(
                "INSERT INTO collections (id, name, dimension, model_name, distance_metric) VALUES (?, ?, ?, ?, ?)",
                (collection_id, name, dimension, model_name, distance_metric.value),
            )

            # Per-collection virtual tables
            conn.execute(
                f"CREATE VIRTUAL TABLE [{self._vec_table(collection_id)}] USING vec0(id TEXT PRIMARY KEY, embedding float[{dimension}])"
            )
            conn.execute(
                f"CREATE VIRTUAL TABLE [{self._fts_table(collection_id)}] USING fts5(content, name, chunk_id UNINDEXED, tokenize='porter unicode61')"
            )

            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise StoreError(f"Collection '{name}' already exists (UNIQUE constraint)") from exc
        except Exception as exc:
            conn.rollback()
            raise StoreError(f"Failed to create collection '{name}': {exc}") from exc

        return Collection(
            id=collection_id,
            name=name,
            dimension=dimension,
            model_name=model_name,
            distance_metric=distance_metric,
        )

    async def get_collection(self, name: str) -> Collection | None:
        """Get a collection by name. Returns None if not found."""
        return await asyncio.to_thread(self._get_collection_sync, name)

    def _get_collection_sync(self, name: str) -> Collection | None:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT id, name, dimension, model_name, distance_metric, created_at, metadata FROM collections WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return Collection(
            id=row[0],
            name=row[1],
            dimension=row[2],
            model_name=row[3],
            distance_metric=DistanceMetric(row[4]),
            created_at=datetime.fromisoformat(row[5]) if row[5] else datetime.now(),
            metadata=json.loads(row[6]) if row[6] else {},
        )

    async def list_collections(self) -> list[Collection]:
        """List all collections."""
        return await asyncio.to_thread(self._list_collections_sync)

    def _list_collections_sync(self) -> list[Collection]:
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT id, name, dimension, model_name, distance_metric, created_at, metadata FROM collections ORDER BY name"
        ).fetchall()
        result = []
        for row in rows:
            result.append(
                Collection(
                    id=row[0],
                    name=row[1],
                    dimension=row[2],
                    model_name=row[3],
                    distance_metric=DistanceMetric(row[4]),
                    created_at=datetime.fromisoformat(row[5]) if row[5] else datetime.now(),
                    metadata=json.loads(row[6]) if row[6] else {},
                )
            )
        return result

    async def delete_collection(self, name: str) -> None:
        """Delete a collection and all its data (chunks, vectors, FTS)."""
        await asyncio.to_thread(self._delete_collection_sync, name)

    def _delete_collection_sync(self, name: str) -> None:
        conn = self._require_conn()
        row = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise StoreError(f"Collection '{name}' not found")
        collection_id = row[0]

        try:
            # Drop virtual tables first (they reference chunks by id)
            conn.execute(f"DROP TABLE IF EXISTS [{self._vec_table(collection_id)}]")
            conn.execute(f"DROP TABLE IF EXISTS [{self._fts_table(collection_id)}]")
            # Delete chunks
            conn.execute("DELETE FROM chunks WHERE collection_id = ?", (collection_id,))
            # Delete collection row
            conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise StoreError(f"Failed to delete collection '{name}': {exc}") from exc

    # ------------------------------------------------------------------
    # Chunk CRUD
    # ------------------------------------------------------------------

    async def add(
        self,
        collection_name: str,
        chunks: list[Chunk],
        embeddings: list[Embedding],
    ) -> None:
        """Add chunks with their embeddings to a collection.

        Inserts into chunks table, vec virtual table, and FTS virtual table
        in a single transaction.
        """
        await asyncio.to_thread(self._add_sync, collection_name, chunks, embeddings)

    def _add_sync(
        self,
        collection_name: str,
        chunks: list[Chunk],
        embeddings: list[Embedding],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise StoreError(f"Mismatched lengths: {len(chunks)} chunks vs {len(embeddings)} embeddings")

        collection_id, dimension = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        vec_table = self._vec_table(collection_id)
        fts_table = self._fts_table(collection_id)

        try:
            for chunk, embedding in zip(chunks, embeddings):
                # Insert into chunks table
                conn.execute(
                    """INSERT INTO chunks
                       (id, collection_id, content, content_type, chunk_type,
                        source_path, start_line, end_line, name, parent, metadata, content_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk.id,
                        collection_id,
                        chunk.content,
                        chunk.content_type.value,
                        chunk.chunk_type,
                        chunk.source.file_path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.name,
                        chunk.parent,
                        json.dumps(chunk.metadata) if chunk.metadata else None,
                        chunk.source.content_hash,
                    ),
                )

                # Insert into vec virtual table
                vec_bytes = _serialize_float32_vec(embedding.to_list())
                conn.execute(
                    f"INSERT INTO [{vec_table}] (id, embedding) VALUES (?, ?)",
                    (chunk.id, vec_bytes),
                )

                # Insert into FTS virtual table
                conn.execute(
                    f"INSERT INTO [{fts_table}] (content, name, chunk_id) VALUES (?, ?, ?)",
                    (chunk.content, chunk.name or "", chunk.id),
                )

            conn.commit()
        except StoreError:
            conn.rollback()
            raise
        except Exception as exc:
            conn.rollback()
            raise StoreError(f"Failed to add chunks to collection '{collection_name}': {exc}") from exc

    async def get(self, collection_name: str, chunk_id: str) -> dict[str, Any] | None:
        """Get a single chunk by ID. Returns a dict or None."""
        return await asyncio.to_thread(self._get_sync, collection_name, chunk_id)

    def _get_sync(self, collection_name: str, chunk_id: str) -> dict[str, Any] | None:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        row = conn.execute(
            """SELECT id, content, content_type, chunk_type, source_path,
                      start_line, end_line, name, parent, metadata, content_hash, created_at
               FROM chunks WHERE id = ? AND collection_id = ?""",
            (chunk_id, collection_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "chunk_id": row[0],
            "content": row[1],
            "content_type": row[2],
            "chunk_type": row[3],
            "source_path": row[4],
            "start_line": row[5],
            "end_line": row[6],
            "name": row[7],
            "parent": row[8],
            "metadata": json.loads(row[9]) if row[9] else {},
            "content_hash": row[10],
            "created_at": row[11],
        }

    async def delete(self, collection_name: str, chunk_ids: list[str]) -> None:
        """Delete specific chunks by ID from all three stores."""
        await asyncio.to_thread(self._delete_sync, collection_name, chunk_ids)

    def _delete_sync(self, collection_name: str, chunk_ids: list[str]) -> None:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        vec_table = self._vec_table(collection_id)
        fts_table = self._fts_table(collection_id)

        try:
            for cid in chunk_ids:
                conn.execute(f"DELETE FROM [{vec_table}] WHERE id = ?", (cid,))
                conn.execute(f"DELETE FROM [{fts_table}] WHERE chunk_id = ?", (cid,))
                conn.execute("DELETE FROM chunks WHERE id = ? AND collection_id = ?", (cid, collection_id))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise StoreError(f"Failed to delete chunks: {exc}") from exc

    async def delete_by_source(self, collection_name: str, source_path: str) -> int:
        """Delete all chunks from a given source path. Returns the count deleted."""
        return await asyncio.to_thread(self._delete_by_source_sync, collection_name, source_path)

    def _delete_by_source_sync(self, collection_name: str, source_path: str) -> int:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        vec_table = self._vec_table(collection_id)
        fts_table = self._fts_table(collection_id)

        # Find chunk IDs for this source
        rows = conn.execute(
            "SELECT id FROM chunks WHERE collection_id = ? AND source_path = ?",
            (collection_id, source_path),
        ).fetchall()

        if not rows:
            return 0

        chunk_ids = [r[0] for r in rows]
        try:
            for cid in chunk_ids:
                conn.execute(f"DELETE FROM [{vec_table}] WHERE id = ?", (cid,))
                conn.execute(f"DELETE FROM [{fts_table}] WHERE chunk_id = ?", (cid,))
                conn.execute("DELETE FROM chunks WHERE id = ?", (cid,))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise StoreError(f"Failed to delete chunks by source '{source_path}': {exc}") from exc

        return len(chunk_ids)

    # ------------------------------------------------------------------
    # KNN Search (sqlite-vec)
    # ------------------------------------------------------------------

    async def search_knn(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[dict[str, Any]]:
        """K-nearest-neighbor search over the vector index.

        Returns a list of dicts with keys: ``chunk_id``, ``score``,
        ``content``, ``content_type``, ``source_path``, etc.
        Results are sorted by similarity (most similar first).
        """
        return await asyncio.to_thread(self._search_knn_sync, collection_name, query_vector, top_k, filters)

    def _search_knn_sync(
        self,
        collection_name: str,
        query_vector: list[float],
        top_k: int,
        filters: SearchFilters | None,
    ) -> list[dict[str, Any]]:
        collection_id, dimension = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        vec_table = self._vec_table(collection_id)

        query_bytes = _serialize_float32_vec(query_vector)

        # First get KNN candidates from vec table
        # sqlite-vec returns rows ordered by distance (ascending)
        vec_rows = conn.execute(
            f"SELECT id, distance FROM [{vec_table}] WHERE embedding MATCH ? AND k = ?",
            (query_bytes, top_k if filters is None else top_k * 5),  # Over-fetch when filtering
        ).fetchall()

        if not vec_rows:
            return []

        # Collect chunk IDs and distances
        candidates: list[tuple[str, float]] = [(row[0], row[1]) for row in vec_rows]

        # Fetch full chunk data and apply filters
        results: list[dict[str, Any]] = []
        for chunk_id, distance in candidates:
            row = conn.execute(
                """SELECT id, content, content_type, chunk_type, source_path,
                          start_line, end_line, name, parent, metadata, content_hash
                   FROM chunks WHERE id = ? AND collection_id = ?""",
                (chunk_id, collection_id),
            ).fetchone()
            if row is None:
                continue

            # Apply filters
            if filters is not None:
                if filters.content_types:
                    type_values = [ct.value for ct in filters.content_types]
                    if row[2] not in type_values:
                        continue
                if filters.source_path_prefix:
                    if row[4] is None or not row[4].startswith(filters.source_path_prefix):
                        continue
                if filters.chunk_types:
                    if row[3] not in filters.chunk_types:
                        continue

            # Convert distance to similarity score (cosine distance → similarity = 1 - distance)
            score = 1.0 - distance

            results.append(
                {
                    "chunk_id": row[0],
                    "score": score,
                    "content": row[1],
                    "content_type": row[2],
                    "chunk_type": row[3],
                    "source_path": row[4],
                    "start_line": row[5],
                    "end_line": row[6],
                    "name": row[7],
                    "parent": row[8],
                    "metadata": json.loads(row[9]) if row[9] else {},
                    "content_hash": row[10],
                }
            )

            if len(results) >= top_k:
                break

        # Already sorted by distance (ascending) from sqlite-vec → sorted by score descending
        return results

    # ------------------------------------------------------------------
    # FTS Search (BM25)
    # ------------------------------------------------------------------

    async def search_fts(
        self,
        collection_name: str,
        query_text: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[dict[str, Any]]:
        """Full-text search using FTS5 BM25 ranking.

        Searches the ``content`` and ``name`` columns.
        Returns a list of dicts in the same format as :meth:`search_knn`.
        """
        return await asyncio.to_thread(self._search_fts_sync, collection_name, query_text, top_k, filters)

    def _search_fts_sync(
        self,
        collection_name: str,
        query_text: str,
        top_k: int,
        filters: SearchFilters | None,
    ) -> list[dict[str, Any]]:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        fts_table = self._fts_table(collection_id)

        # FTS5 query: search content and name columns
        # bm25() returns negative scores (lower = more relevant), so we negate
        try:
            fts_rows = conn.execute(
                f"""SELECT chunk_id, -bm25([{fts_table}]) AS score
                    FROM [{fts_table}]
                    WHERE [{fts_table}] MATCH ?
                    ORDER BY score DESC
                    LIMIT ?""",
                (query_text, top_k * 5 if filters else top_k),
            ).fetchall()
        except sqlite3.OperationalError:
            # Bad FTS query syntax → no results
            return []

        if not fts_rows:
            return []

        results: list[dict[str, Any]] = []
        for chunk_id, score in fts_rows:
            row = conn.execute(
                """SELECT id, content, content_type, chunk_type, source_path,
                          start_line, end_line, name, parent, metadata, content_hash
                   FROM chunks WHERE id = ? AND collection_id = ?""",
                (chunk_id, collection_id),
            ).fetchone()
            if row is None:
                continue

            # Apply filters
            if filters is not None:
                if filters.content_types:
                    type_values = [ct.value for ct in filters.content_types]
                    if row[2] not in type_values:
                        continue
                if filters.source_path_prefix:
                    if row[4] is None or not row[4].startswith(filters.source_path_prefix):
                        continue
                if filters.chunk_types:
                    if row[3] not in filters.chunk_types:
                        continue

            results.append(
                {
                    "chunk_id": row[0],
                    "score": score,
                    "content": row[1],
                    "content_type": row[2],
                    "chunk_type": row[3],
                    "source_path": row[4],
                    "start_line": row[5],
                    "end_line": row[6],
                    "name": row[7],
                    "parent": row[8],
                    "metadata": json.loads(row[9]) if row[9] else {},
                    "content_hash": row[10],
                }
            )

            if len(results) >= top_k:
                break

        return results

    # ------------------------------------------------------------------
    # Stats & Info
    # ------------------------------------------------------------------

    async def count(self, collection_name: str) -> int:
        """Count the number of chunks in a collection."""
        return await asyncio.to_thread(self._count_sync, collection_name)

    def _count_sync(self, collection_name: str) -> int:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        row = conn.execute("SELECT COUNT(*) FROM chunks WHERE collection_id = ?", (collection_id,)).fetchone()
        return row[0] if row else 0

    async def list_sources(self, collection_name: str) -> list[str]:
        """List distinct source paths in a collection."""
        return await asyncio.to_thread(self._list_sources_sync, collection_name)

    def _list_sources_sync(self, collection_name: str) -> list[str]:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT DISTINCT source_path FROM chunks WHERE collection_id = ? AND source_path IS NOT NULL ORDER BY source_path",
            (collection_id,),
        ).fetchall()
        return [r[0] for r in rows]

    async def stats(self, collection_name: str) -> CollectionStats:
        """Get statistics for a collection."""
        return await asyncio.to_thread(self._stats_sync, collection_name)

    def _stats_sync(self, collection_name: str) -> CollectionStats:
        collection_id, dimension = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()

        # Get model_name
        row = conn.execute("SELECT model_name FROM collections WHERE id = ?", (collection_id,)).fetchone()
        model_name = row[0] if row else ""

        # Chunk count
        row = conn.execute("SELECT COUNT(*) FROM chunks WHERE collection_id = ?", (collection_id,)).fetchone()
        chunk_count = row[0] if row else 0

        # Source count
        row = conn.execute(
            "SELECT COUNT(DISTINCT source_path) FROM chunks WHERE collection_id = ? AND source_path IS NOT NULL",
            (collection_id,),
        ).fetchone()
        source_count = row[0] if row else 0

        return CollectionStats(
            name=collection_name,
            chunk_count=chunk_count,
            source_count=source_count,
            dimension=dimension,
            model_name=model_name,
        )

    async def has_content_hash(self, collection_name: str, content_hash: str) -> bool:
        """Check if a content hash exists in a collection."""
        return await asyncio.to_thread(self._has_content_hash_sync, collection_name, content_hash)

    def _has_content_hash_sync(self, collection_name: str, content_hash: str) -> bool:
        collection_id, _ = self._resolve_collection_sync(collection_name)
        conn = self._require_conn()
        row = conn.execute(
            "SELECT 1 FROM chunks WHERE collection_id = ? AND content_hash = ? LIMIT 1",
            (collection_id, content_hash),
        ).fetchone()
        return row is not None
