from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.model.config import SearchConfig
from remora.core.services.search import SearchService


class _MockEmbeddyClient:
    fail_health = False

    def __init__(self, base_url: str = "", *, timeout: float = 30.0):
        self.base_url = base_url
        self.timeout = timeout
        self.closed = False
        self.last_search_args: tuple | None = None
        self.last_reindex_args: tuple | None = None
        self.last_delete_source_args: tuple | None = None
        self.last_ingest_directory_args: tuple | None = None

    async def health(self) -> dict:
        if self.fail_health:
            raise OSError("health failed")
        return {"status": "ok"}

    async def close(self) -> None:
        self.closed = True

    async def search(self, query: str, collection: str = "default", **kwargs) -> dict:
        self.last_search_args = (query, collection, kwargs)
        return {
            "results": [
                {
                    "chunk_id": "c1",
                    "content": "hello",
                    "score": 0.9,
                    "source_path": "src/foo.py",
                }
            ],
            "query": query,
            "collection": collection,
        }

    async def find_similar(self, chunk_id: str, collection: str = "default", **kwargs) -> dict:
        return {
            "results": [{"chunk_id": chunk_id, "score": 0.8}],
            "collection": collection,
            "kwargs": kwargs,
        }

    async def reindex(self, path: str, collection: str = "default") -> dict:
        self.last_reindex_args = (path, collection)
        return {"files_processed": 1}

    async def delete_source(self, source_path: str, collection: str = "default") -> dict:
        self.last_delete_source_args = (source_path, collection)
        return {"deleted_count": 1}

    async def ingest_directory(
        self,
        path: str,
        collection: str = "default",
        *,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> dict:
        self.last_ingest_directory_args = (path, collection, include, exclude)
        return {"files_processed": 2, "chunks_created": 4, "errors": []}


@pytest.mark.asyncio
async def test_search_service_disabled_returns_empty_results(tmp_path: Path) -> None:
    service = SearchService(SearchConfig(enabled=False), tmp_path)
    await service.initialize()

    assert service.available is False
    assert await service.search("auth") == []
    assert await service.find_similar("chunk-1") == []
    assert await service.index_directory(str(tmp_path)) == {"error": "search service not available"}


@pytest.mark.asyncio
async def test_search_service_no_embeddy_graceful_degradation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(SearchService, "_load_remote_client_class", lambda _self: None)

    service = SearchService(SearchConfig(enabled=True, mode="remote"), tmp_path)
    await service.initialize()
    assert service.available is False
    assert await service.search("query") == []


@pytest.mark.asyncio
async def test_search_service_remote_mode_connected(tmp_path: Path, monkeypatch) -> None:
    _MockEmbeddyClient.fail_health = False
    monkeypatch.setattr(
        SearchService,
        "_load_remote_client_class",
        lambda _self: _MockEmbeddyClient,
    )

    service = SearchService(
        SearchConfig(enabled=True, mode="remote", embeddy_url="http://localhost:8585"),
        tmp_path,
    )
    await service.initialize()
    assert service.available is True

    results = await service.search("auth", collection="code", top_k=5, mode="hybrid")
    assert len(results) == 1
    assert results[0]["chunk_id"] == "c1"

    similar = await service.find_similar("c1", collection="code", top_k=3)
    assert similar
    assert similar[0]["chunk_id"] == "c1"

    await service.close()
    assert service._client is not None
    assert service._client.closed is True


@pytest.mark.asyncio
async def test_search_service_remote_mode_unreachable(tmp_path: Path, monkeypatch) -> None:
    _MockEmbeddyClient.fail_health = True
    monkeypatch.setattr(
        SearchService,
        "_load_remote_client_class",
        lambda _self: _MockEmbeddyClient,
    )

    service = SearchService(SearchConfig(enabled=True, mode="remote"), tmp_path)
    await service.initialize()
    assert service.available is False
    assert await service.search("query") == []


def test_collection_for_file() -> None:
    service = SearchService(SearchConfig(enabled=False), Path("."))
    assert service.collection_for_file("src/a.py") == "code"
    assert service.collection_for_file("README.md") == "docs"
    assert service.collection_for_file("notes.xyz") == "code"


@pytest.mark.asyncio
async def test_index_file_delegates_to_client(tmp_path: Path, monkeypatch) -> None:
    _MockEmbeddyClient.fail_health = False
    monkeypatch.setattr(
        SearchService,
        "_load_remote_client_class",
        lambda _self: _MockEmbeddyClient,
    )

    service = SearchService(SearchConfig(enabled=True, mode="remote"), tmp_path)
    await service.initialize()
    await service.index_file("src/foo.py")
    assert service._client is not None
    assert service._client.last_reindex_args == ("src/foo.py", "code")


@pytest.mark.asyncio
async def test_delete_source_delegates_to_client(tmp_path: Path, monkeypatch) -> None:
    _MockEmbeddyClient.fail_health = False
    monkeypatch.setattr(
        SearchService,
        "_load_remote_client_class",
        lambda _self: _MockEmbeddyClient,
    )

    service = SearchService(SearchConfig(enabled=True, mode="remote"), tmp_path)
    await service.initialize()
    await service.delete_source("src/foo.py")
    assert service._client is not None
    assert service._client.last_delete_source_args == ("src/foo.py", "code")


@pytest.mark.asyncio
async def test_index_directory_delegates_to_client(tmp_path: Path, monkeypatch) -> None:
    _MockEmbeddyClient.fail_health = False
    monkeypatch.setattr(
        SearchService,
        "_load_remote_client_class",
        lambda _self: _MockEmbeddyClient,
    )

    service = SearchService(SearchConfig(enabled=True, mode="remote"), tmp_path)
    await service.initialize()
    stats = await service.index_directory(
        str(tmp_path),
        collection="docs",
        include=["*.md"],
        exclude=["*.tmp"],
    )
    assert service._client is not None
    assert service._client.last_ingest_directory_args == (
        str(tmp_path),
        "docs",
        ["*.md"],
        ["*.tmp"],
    )
    assert stats["files_processed"] == 2
