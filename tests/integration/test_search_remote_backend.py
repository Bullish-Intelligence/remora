from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from remora.core.events import EventBus, EventStore
from remora.core.model.config import SearchConfig
from remora.core.services.search import SearchService
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.web.server import create_app

_REMOTE_SEARCH_URL = os.getenv("REMORA_TEST_SEARCH_URL", "").strip()
_REMOTE_SEARCH_SKIP_REASON = "REMORA_TEST_SEARCH_URL not set - skipping remote search integration"


def _assert_result_shape(item: dict[str, Any]) -> None:
    assert isinstance(item, dict)
    assert "chunk_id" in item
    assert "score" in item
    assert isinstance(item["chunk_id"], str)
    assert isinstance(item["score"], int | float)


@pytest_asyncio.fixture
async def remote_search_service(tmp_path: Path):
    if not _REMOTE_SEARCH_URL:
        pytest.skip(_REMOTE_SEARCH_SKIP_REASON)

    service = SearchService(
        SearchConfig(
            enabled=True,
            mode="remote",
            embeddy_url=_REMOTE_SEARCH_URL,
            timeout=20.0,
        ),
        tmp_path,
    )
    await service.initialize()
    if not service.available:
        await service.close()
        pytest.skip(f"Remote search backend unavailable at {_REMOTE_SEARCH_URL}")

    try:
        yield service
    finally:
        await service.close()


@pytest_asyncio.fixture
async def remote_search_web_client(tmp_path: Path, remote_search_service: SearchService):
    db = await open_database(tmp_path / "search-web.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()

    app = create_app(
        event_store=event_store,
        node_store=node_store,
        event_bus=event_bus,
        search_service=remote_search_service,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await db.close()


@pytest.mark.asyncio
async def test_remote_search_service_initializes_with_real_backend(
    remote_search_service: SearchService,
) -> None:
    assert remote_search_service.available is True


@pytest.mark.asyncio
async def test_remote_search_service_returns_structured_results(
    remote_search_service: SearchService,
) -> None:
    results = await remote_search_service.search(
        query="order validation",
        collection="code",
        top_k=5,
        mode="hybrid",
    )
    assert isinstance(results, list)
    for item in results:
        _assert_result_shape(item)


@pytest.mark.asyncio
async def test_remote_search_service_index_file_and_delete_source(
    tmp_path: Path,
    remote_search_service: SearchService,
) -> None:
    source = tmp_path / "src" / "orders.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "def create_order(total: float) -> float:\n    return total * 1.07\n",
        encoding="utf-8",
    )

    await remote_search_service.index_file(str(source), collection="code")
    await remote_search_service.delete_source(str(source), collection="code")


@pytest.mark.asyncio
async def test_api_search_route_end_to_end_with_remote_backend(
    remote_search_web_client: httpx.AsyncClient,
) -> None:
    response = await remote_search_web_client.post(
        "/api/search",
        json={
            "query": "order validation",
            "collection": "code",
            "top_k": 5,
            "mode": "hybrid",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "order validation"
    assert payload["collection"] == "code"
    assert payload["mode"] == "hybrid"
    assert isinstance(payload["elapsed_ms"], int | float)
    assert isinstance(payload["results"], list)
    assert payload["total_results"] == len(payload["results"])
    for item in payload["results"]:
        _assert_result_shape(item)
