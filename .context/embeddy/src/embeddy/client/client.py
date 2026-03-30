# src/embeddy/client/client.py
"""Async HTTP client for the embeddy server.

Provides :class:`EmbeddyClient` — a thin, typed wrapper around httpx that
mirrors the server API.  Consumers (e.g. remora) use this instead of crafting
raw HTTP requests.

Usage::

    async with EmbeddyClient("http://gpu-machine:8585") as client:
        result = await client.search("how does auth work?", collection="code")
        for hit in result["results"]:
            print(hit["content"])
"""

from __future__ import annotations

from typing import Any

import httpx

from embeddy.exceptions import EmbeddyError


class EmbeddyClient:
    """Async HTTP client for the embeddy REST API.

    Args:
        base_url: Server base URL (default ``http://localhost:8585``).
        timeout: Request timeout in seconds (default 30).
        transport: Optional httpx transport override (used for testing with
            ASGITransport).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8585",
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        kwargs: dict[str, Any] = {
            "base_url": base_url,
            "timeout": timeout,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.AsyncClient(**kwargs)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout(self) -> float:
        return self._timeout

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> EmbeddyClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api(self, path: str) -> str:
        """Build the full API path."""
        return f"/api/v1{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a request and return parsed JSON, raising on errors."""
        resp = await self._http.request(
            method,
            self._api(path),
            json=json,
            params=params,
        )
        data = resp.json()

        if resp.status_code >= 400:
            # Server returns {"error": ..., "message": ...} for errors
            if isinstance(data, dict):
                error_key = data.get("error", "unknown_error")
                message = data.get("message", str(data))
                raise EmbeddyError(f"{error_key}: {message}")
            raise EmbeddyError(f"HTTP {resp.status_code}: {data}")

        return data  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Health / Info
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """GET /health — health check."""
        return await self._request("GET", "/health")

    async def info(self) -> dict[str, Any]:
        """GET /info — server info (version, model, dimension)."""
        return await self._request("GET", "/info")

    # ------------------------------------------------------------------
    # Embed
    # ------------------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        instruction: str | None = None,
    ) -> dict[str, Any]:
        """POST /embed — embed a batch of text inputs.

        Args:
            texts: List of text strings to embed.
            instruction: Optional instruction for the embedding model.

        Returns:
            Dict with ``embeddings``, ``dimension``, ``model``, ``elapsed_ms``.
        """
        body: dict[str, Any] = {
            "inputs": [{"text": t} for t in texts],
        }
        if instruction is not None:
            body["instruction"] = instruction
        return await self._request("POST", "/embed", json=body)

    async def embed_query(self, text: str, *, instruction: str | None = None) -> dict[str, Any]:
        """POST /embed/query — embed a single query input.

        Args:
            text: The query text.
            instruction: Optional instruction override.

        Returns:
            Dict with ``embedding``, ``dimension``, ``model``, ``elapsed_ms``.
        """
        body: dict[str, Any] = {"input": {"text": text}}
        if instruction is not None:
            body["instruction"] = instruction
        return await self._request("POST", "/embed/query", json=body)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        collection: str = "default",
        *,
        top_k: int = 10,
        mode: str = "hybrid",
        filters: dict[str, Any] | None = None,
        min_score: float | None = None,
        hybrid_alpha: float = 0.7,
        fusion: str = "rrf",
    ) -> dict[str, Any]:
        """POST /search — search a collection.

        Returns:
            Dict with ``results``, ``query``, ``collection``, ``total_results``,
            ``mode``, ``elapsed_ms``.
        """
        body: dict[str, Any] = {
            "query": query,
            "collection": collection,
            "top_k": top_k,
            "mode": mode,
            "hybrid_alpha": hybrid_alpha,
            "fusion": fusion,
        }
        if filters is not None:
            body["filters"] = filters
        if min_score is not None:
            body["min_score"] = min_score
        return await self._request("POST", "/search", json=body)

    async def find_similar(
        self,
        chunk_id: str,
        collection: str = "default",
        *,
        top_k: int = 10,
        exclude_self: bool = True,
    ) -> dict[str, Any]:
        """POST /search/similar — find chunks similar to an existing chunk.

        Returns:
            Dict with ``results``, ``query``, ``collection``, ``total_results``,
            ``mode``, ``elapsed_ms``.
        """
        body: dict[str, Any] = {
            "chunk_id": chunk_id,
            "collection": collection,
            "top_k": top_k,
            "exclude_self": exclude_self,
        }
        return await self._request("POST", "/search/similar", json=body)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    async def ingest_text(
        self,
        text: str,
        collection: str = "default",
        *,
        source: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """POST /ingest/text — ingest raw text.

        Returns:
            Dict with ingest stats (files_processed, chunks_created, etc.).
        """
        body: dict[str, Any] = {"text": text, "collection": collection}
        if source is not None:
            body["source"] = source
        if content_type is not None:
            body["content_type"] = content_type
        return await self._request("POST", "/ingest/text", json=body)

    async def ingest_file(
        self,
        path: str,
        collection: str = "default",
        *,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """POST /ingest/file — ingest a file by path.

        Returns:
            Dict with ingest stats.
        """
        body: dict[str, Any] = {"path": path, "collection": collection}
        if content_type is not None:
            body["content_type"] = content_type
        return await self._request("POST", "/ingest/file", json=body)

    async def ingest_directory(
        self,
        path: str,
        collection: str = "default",
        *,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        """POST /ingest/directory — ingest all files in a directory.

        Returns:
            Dict with ingest stats.
        """
        body: dict[str, Any] = {
            "path": path,
            "collection": collection,
            "recursive": recursive,
        }
        if include is not None:
            body["include"] = include
        if exclude is not None:
            body["exclude"] = exclude
        return await self._request("POST", "/ingest/directory", json=body)

    async def reindex(
        self,
        path: str,
        collection: str = "default",
    ) -> dict[str, Any]:
        """POST /ingest/reindex — reindex a file (delete old + re-ingest).

        Returns:
            Dict with ingest stats.
        """
        body: dict[str, Any] = {"path": path, "collection": collection}
        return await self._request("POST", "/ingest/reindex", json=body)

    async def delete_source(
        self,
        source_path: str,
        collection: str = "default",
    ) -> dict[str, Any]:
        """DELETE /ingest/source — delete all chunks from a source.

        Returns:
            Dict with ``deleted_count``.
        """
        body: dict[str, Any] = {
            "source_path": source_path,
            "collection": collection,
        }
        return await self._request("DELETE", "/ingest/source", json=body)

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    async def list_collections(self) -> dict[str, Any]:
        """GET /collections — list all collections.

        Returns:
            Dict with ``collections`` list.
        """
        return await self._request("GET", "/collections")

    async def create_collection(
        self,
        name: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /collections — create a new collection.

        Returns:
            Dict with collection info (id, name, dimension, model_name, metadata).
        """
        body: dict[str, Any] = {"name": name}
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request("POST", "/collections", json=body)

    async def get_collection(self, name: str) -> dict[str, Any]:
        """GET /collections/{name} — get a single collection.

        Returns:
            Dict with collection info.

        Raises:
            EmbeddyError: If the collection is not found (404).
        """
        return await self._request("GET", f"/collections/{name}")

    async def delete_collection(self, name: str) -> dict[str, Any]:
        """DELETE /collections/{name} — delete a collection.

        Returns:
            Dict with confirmation message.

        Raises:
            EmbeddyError: If the collection is not found (404).
        """
        return await self._request("DELETE", f"/collections/{name}")

    async def collection_sources(self, name: str) -> dict[str, Any]:
        """GET /collections/{name}/sources — list source paths.

        Returns:
            Dict with ``sources`` list.

        Raises:
            EmbeddyError: If the collection is not found (404).
        """
        return await self._request("GET", f"/collections/{name}/sources")

    async def collection_stats(self, name: str) -> dict[str, Any]:
        """GET /collections/{name}/stats — get collection statistics.

        Returns:
            Dict with stats (name, chunk_count, source_count, dimension, etc.).

        Raises:
            EmbeddyError: If the collection is not found (404).
        """
        return await self._request("GET", f"/collections/{name}/stats")

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    async def get_chunk(
        self,
        chunk_id: str,
        *,
        collection: str = "default",
    ) -> dict[str, Any]:
        """GET /chunks/{chunk_id} — get a chunk by ID.

        Returns:
            Dict with chunk data (chunk_id, content, source_path, etc.).

        Raises:
            EmbeddyError: If the chunk is not found (404).
        """
        return await self._request("GET", f"/chunks/{chunk_id}", params={"collection": collection})

    async def delete_chunk(
        self,
        chunk_id: str,
        *,
        collection: str = "default",
    ) -> dict[str, Any]:
        """DELETE /chunks/{chunk_id} — delete a chunk.

        Returns:
            Dict with confirmation message.
        """
        return await self._request("DELETE", f"/chunks/{chunk_id}", params={"collection": collection})
