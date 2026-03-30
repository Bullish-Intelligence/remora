from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from structured_agents import Message
from tests.factories import make_node

from remora import __version__
from remora.core.events import (
    AgentMessageEvent,
    EventBus,
    EventStore,
    RewriteProposalEvent,
)
from remora.core.model.config import Config, InfraConfig
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import CairnWorkspaceService
from remora.web.server import create_app


async def _read_sse_event_lines(response: httpx.Response) -> list[str]:
    lines: list[str] = []
    async for line in response.aiter_lines():
        if not line:
            if lines:
                return lines
            continue
        if line.startswith(":"):
            continue
        lines.append(line)
    raise AssertionError("SSE stream closed before event payload was received")


@pytest_asyncio.fixture
async def web_env(tmp_path: Path):
    db = await open_database(tmp_path / "web.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()

    source_path = tmp_path / "src" / "app.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def a():\n    return 1\n", encoding="utf-8")

    node = make_node(
        "src/app.py::a",
        file_path=str(source_path),
        text="def a():\n    return 1\n",
        start_line=1,
        end_line=2,
    )
    await node_store.upsert_node(node)

    broker = HumanInputBroker()
    app = create_app(
        event_store,
        node_store,
        event_bus,
        human_input_broker=broker,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, node_store, event_store, source_path

    await db.close()


@pytest_asyncio.fixture
async def proposal_web_env(tmp_path: Path):
    db = await open_database(tmp_path / "proposal-web.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()

    source_path = tmp_path / "src" / "app.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def a():\n    return 1\n", encoding="utf-8")

    node = make_node(
        "src/app.py::a",
        file_path=str(source_path),
        text="def a():\n    return 1\n",
        start_line=1,
        end_line=2,
        status="awaiting_review",
    )
    await node_store.upsert_node(node)

    config = Config(infra=InfraConfig(workspace_root=".remora-web-proposals"))
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    workspace = await workspace_service.get_agent_workspace(node.node_id)
    await workspace.write("source/src/app.py::a", "def a():\n    return 2\n")
    await event_store.append(
        RewriteProposalEvent(
            agent_id=node.node_id,
            proposal_id="proposal-1",
            files=("source/src/app.py::a",),
            reason="Improve return value",
        )
    )

    app = create_app(
        event_store,
        node_store,
        event_bus,
        workspace_service=workspace_service,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, node_store, event_store, workspace_service, source_path

    await workspace_service.close()
    await db.close()


@pytest_asyncio.fixture
async def companion_web_env(tmp_path: Path):
    db = await open_database(tmp_path / "companion-web.db")
    event_bus = EventBus()
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus)
    await event_store.create_tables()

    config = Config(infra=InfraConfig(workspace_root=".remora-web-companion"))
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    app = create_app(
        event_store,
        node_store,
        event_bus,
        workspace_service=workspace_service,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield {
            "client": client,
            "node_store": node_store,
            "workspace_service": workspace_service,
        }

    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_api_nodes_returns_list(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/nodes")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload and payload[0]["node_id"] == "src/app.py::a"


@pytest.mark.asyncio
async def test_api_node_by_id(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/nodes/src/app.py::a")
    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "src/app.py::a"


@pytest.mark.asyncio
async def test_api_node_not_found(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/nodes/missing")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_node_companion_empty(companion_web_env) -> None:
    env = companion_web_env
    node = make_node("src/validate.py::validate", file_path="src/validate.py")
    await env["node_store"].upsert_node(node)

    response = await env["client"].get(f"/api/nodes/{node.node_id}/companion")
    assert response.status_code == 200
    assert response.json() == {}


@pytest.mark.asyncio
async def test_api_node_companion_with_data(companion_web_env) -> None:
    env = companion_web_env
    node = make_node("src/validate.py::validate", file_path="src/validate.py")
    await env["node_store"].upsert_node(node)

    workspace = await env["workspace_service"].get_agent_workspace(node.node_id)
    await workspace.kv_set("companion/chat_index", [{"summary": "test", "tags": ["bug"]}])
    await workspace.kv_set("companion/reflections", [{"insight": "needs fix"}])

    response = await env["client"].get(f"/api/nodes/{node.node_id}/companion")
    assert response.status_code == 200
    data = response.json()
    assert "chat_index" in data
    assert "reflections" in data
    assert data["chat_index"][0]["summary"] == "test"


@pytest.mark.asyncio
async def test_api_edges(web_env) -> None:
    client, node_store, _event_store, source_path = web_env
    other = make_node(
        "src/app.py::b",
        file_path=str(source_path),
        text="def b():\n    return 2\n",
        start_line=1,
        end_line=2,
    )
    await node_store.upsert_node(other)
    await node_store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    response = await client.get("/api/nodes/src/app.py::a/edges")
    assert response.status_code == 200
    payload = response.json()
    assert payload and payload[0]["edge_type"] == "calls"


@pytest.mark.asyncio
async def test_api_all_edges(web_env) -> None:
    client, node_store, _event_store, source_path = web_env
    other = make_node(
        "src/app.py::b",
        file_path=str(source_path),
        text="def b():\n    return 2\n",
        start_line=1,
        end_line=2,
    )
    await node_store.upsert_node(other)
    await node_store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    response = await client.get("/api/edges")
    assert response.status_code == 200
    payload = response.json()
    assert payload and payload[0]["edge_type"] == "calls"


@pytest.mark.asyncio
async def test_api_node_relationships_filters_out_contains_by_default(web_env) -> None:
    client, node_store, _event_store, source_path = web_env
    importer = make_node(
        "src/app.py::importer",
        file_path=str(source_path),
        text="def importer():\n    return 1\n",
    )
    dependency = make_node(
        "src/models.py::Config",
        file_path="src/models.py",
        text="class Config:\n    pass\n",
    )
    await node_store.upsert_node(importer)
    await node_store.upsert_node(dependency)
    await node_store.add_edge(importer.node_id, dependency.node_id, "imports")
    await node_store.add_edge(importer.node_id, dependency.node_id, "contains")

    response = await client.get(f"/api/nodes/{importer.node_id}/relationships")
    assert response.status_code == 200
    payload = response.json()
    assert payload == [
        {"from_id": importer.node_id, "to_id": dependency.node_id, "edge_type": "imports"}
    ]


@pytest.mark.asyncio
async def test_api_node_relationships_supports_type_filter(web_env) -> None:
    client, node_store, _event_store, source_path = web_env
    importer = make_node(
        "src/app.py::importer2",
        file_path=str(source_path),
        text="def importer2():\n    return 1\n",
    )
    dependency = make_node(
        "src/models.py::Base",
        file_path="src/models.py",
        text="class Base:\n    pass\n",
    )
    await node_store.upsert_node(importer)
    await node_store.upsert_node(dependency)
    await node_store.add_edge(importer.node_id, dependency.node_id, "imports")
    await node_store.add_edge(importer.node_id, dependency.node_id, "inherits")

    response = await client.get(f"/api/nodes/{importer.node_id}/relationships?type=inherits")
    assert response.status_code == 200
    assert response.json() == [
        {"from_id": importer.node_id, "to_id": dependency.node_id, "edge_type": "inherits"}
    ]


@pytest.mark.asyncio
async def test_api_chat_emits_agent_message_event(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    response = await client.post(
        "/api/chat",
        json={"node_id": "src/app.py::a", "message": "hello"},
    )
    assert response.status_code == 200

    events = await event_store.get_events(limit=10)
    assert any(
        event["event_type"] == "agent_message"
        and event["payload"].get("from_agent") == "user"
        and event["payload"].get("to_agent") == "src/app.py::a"
        and event["payload"].get("content") == "hello"
        for event in events
    )


@pytest.mark.asyncio
async def test_api_chat_missing_node_returns_404(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.post(
        "/api/chat",
        json={"node_id": "missing-node", "message": "hello"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_chat_accepts_message_at_exact_max_length(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env
    app = create_app(
        event_store,
        node_store,
        EventBus(),
        chat_message_max_chars=5,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/chat",
            json={"node_id": "src/app.py::a", "message": "hello"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_api_chat_rejects_message_above_max_length(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env
    app = create_app(
        event_store,
        node_store,
        EventBus(),
        chat_message_max_chars=5,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/chat",
            json={"node_id": "src/app.py::a", "message": "hello!"},
        )
    assert response.status_code == 413
    payload = response.json()
    assert payload == {
        "error": "message_too_long",
        "message": "message exceeds max length",
        "max_chars": 5,
        "received_chars": 6,
    }


@pytest.mark.asyncio
async def test_api_respond_requires_request_id_and_response(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.post(
        "/api/nodes/src/app.py::a/respond",
        json={"request_id": "", "response": ""},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_respond_returns_404_when_request_not_pending(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.post(
        "/api/nodes/src/app.py::a/respond",
        json={"request_id": "missing", "response": "yes"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_respond_resolves_pending_request_and_emits_event(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    # Access the broker that was wired into the app via create_app
    broker: HumanInputBroker = client._transport.app.state.deps.human_input_broker
    future = broker.create_future("req-1")

    response = await client.post(
        "/api/nodes/src/app.py::a/respond",
        json={"request_id": "req-1", "response": "approved"},
    )
    assert response.status_code == 200
    assert future.done()
    assert future.result() == "approved"

    events = await event_store.get_events(limit=5)
    assert any(
        event["event_type"] == "human_input_response"
        and event["payload"].get("request_id") == "req-1"
        and event["payload"].get("response") == "approved"
        for event in events
    )


@pytest.mark.asyncio
async def test_api_proposals_lists_pending_nodes(proposal_web_env) -> None:
    client, _node_store, _event_store, _workspace_service, _source_path = proposal_web_env
    response = await client.get("/api/proposals")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload
    assert payload[0]["node_id"] == "src/app.py::a"
    assert payload[0]["proposal_id"] == "proposal-1"


@pytest.mark.asyncio
async def test_api_proposal_diff_returns_old_and_new_sources(proposal_web_env) -> None:
    client, _node_store, _event_store, _workspace_service, _source_path = proposal_web_env
    response = await client.get("/api/proposals/src/app.py::a/diff")
    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "src/app.py::a"
    assert payload["proposal_id"] == "proposal-1"
    assert payload["diffs"]
    assert payload["diffs"][0]["old"] == "def a():\n    return 1\n"
    assert payload["diffs"][0]["new"] == "def a():\n    return 2\n"


@pytest.mark.asyncio
async def test_api_proposal_accept_materializes_workspace_and_emits_events(
    proposal_web_env,
) -> None:
    client, _node_store, event_store, _workspace_service, source_path = proposal_web_env
    response = await client.post("/api/proposals/src/app.py::a/accept", json={})
    assert response.status_code == 200
    assert source_path.read_text(encoding="utf-8") == "def a():\n    return 2\n"

    events = await event_store.get_events(limit=20)
    rewrite_accepted = next(
        event
        for event in events
        if event["event_type"] == "rewrite_accepted"
        and event["payload"].get("proposal_id") == "proposal-1"
    )
    content_changed = next(
        event
        for event in events
        if event["event_type"] == "content_changed"
        and event["payload"].get("path") == str(source_path)
    )
    assert rewrite_accepted["id"] < content_changed["id"]


@pytest.mark.asyncio
async def test_api_proposal_reject_emits_rejected_event(proposal_web_env) -> None:
    client, _node_store, event_store, _workspace_service, _source_path = proposal_web_env
    response = await client.post(
        "/api/proposals/src/app.py::a/reject",
        json={"feedback": "Try a smaller change"},
    )
    assert response.status_code == 200

    events = await event_store.get_events(limit=20)
    rejected = next(event for event in events if event["event_type"] == "rewrite_rejected")
    assert rejected["payload"]["feedback"] == "Try a smaller change"


@pytest.mark.asyncio
async def test_api_proposal_diff_rejects_path_traversal(proposal_web_env) -> None:
    client, _node_store, event_store, workspace_service, _source_path = proposal_web_env
    workspace = await workspace_service.get_agent_workspace("src/app.py::a")
    await workspace.write("source/../../escape.py", "print('oops')\n")
    await event_store.append(
        RewriteProposalEvent(
            agent_id="src/app.py::a",
            proposal_id="proposal-traversal",
            files=("source/../../escape.py",),
            reason="malicious",
        )
    )

    response = await client.get("/api/proposals/src/app.py::a/diff")
    assert response.status_code == 400
    assert "Path traversal attempt" in response.json()["error"]


@pytest.mark.asyncio
async def test_api_proposal_accept_rejects_path_traversal(proposal_web_env) -> None:
    client, _node_store, event_store, workspace_service, _source_path = proposal_web_env
    workspace = await workspace_service.get_agent_workspace("src/app.py::a")
    await workspace.write("source/../../escape.py", "print('oops')\n")
    await event_store.append(
        RewriteProposalEvent(
            agent_id="src/app.py::a",
            proposal_id="proposal-traversal",
            files=("source/../../escape.py",),
            reason="malicious",
        )
    )

    response = await client.post("/api/proposals/src/app.py::a/accept", json={})
    assert response.status_code == 400
    assert "Path traversal attempt" in response.json()["error"]


@pytest.mark.asyncio
async def test_chat_rate_limit_allows_within_limit(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    statuses = []
    for idx in range(10):
        response = await client.post(
            "/api/chat",
            json={"node_id": "src/app.py::a", "message": f"msg-{idx}"},
        )
        statuses.append(response.status_code)
    assert statuses == [200] * 10


@pytest.mark.asyncio
async def test_chat_rate_limit_blocks_excess(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    for idx in range(10):
        response = await client.post(
            "/api/chat",
            json={"node_id": "src/app.py::a", "message": f"msg-{idx}"},
        )
        assert response.status_code == 200

    blocked = await client.post(
        "/api/chat",
        json={"node_id": "src/app.py::a", "message": "overflow"},
    )
    assert blocked.status_code == 429
    assert blocked.json() == {
        "error": "rate_limit_exceeded",
        "message": "Rate limit exceeded. Try again later.",
    }


@pytest.mark.asyncio
async def test_csrf_rejects_non_local_origin_for_post(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.post(
        "/api/chat",
        json={"node_id": "src/app.py::a", "message": "hello"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "CSRF rejected"


@pytest.mark.asyncio
async def test_csrf_allows_localhost_origin_for_post(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.post(
        "/api/chat",
        json={"node_id": "src/app.py::a", "message": "hello"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_api_events(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    await event_store.append(
        AgentMessageEvent(
            from_agent="user",
            to_agent="src/app.py::a",
            content="ping",
            correlation_id="corr-events-1",
            tags=("chat",),
        )
    )

    response = await client.get("/api/events")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert payload and payload[0]["event_type"] == "agent_message"
    assert set(payload[0].keys()) == {
        "event_type",
        "timestamp",
        "correlation_id",
        "tags",
        "payload",
    }
    assert payload[0]["correlation_id"] == "corr-events-1"
    assert payload[0]["tags"] == ["chat"]
    assert payload[0]["payload"]["content"] == "ping"


@pytest.mark.asyncio
async def test_api_events_supports_type_and_correlation_filters(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    await event_store.append(
        AgentMessageEvent(
            from_agent="user",
            to_agent="src/app.py::a",
            content="match-1",
            correlation_id="corr-events-match",
        )
    )
    await event_store.append(
        AgentMessageEvent(
            from_agent="user",
            to_agent="src/app.py::a",
            content="skip-correlation",
            correlation_id="corr-events-other",
        )
    )

    by_type = await client.get("/api/events?event_type=agent_message")
    assert by_type.status_code == 200
    type_payload = by_type.json()
    assert isinstance(type_payload, list)
    assert type_payload
    assert all(item["event_type"] == "agent_message" for item in type_payload)

    by_corr = await client.get("/api/events?correlation_id=corr-events-match")
    assert by_corr.status_code == 200
    corr_payload = by_corr.json()
    assert isinstance(corr_payload, list)
    assert len(corr_payload) == 1
    assert corr_payload[0]["payload"]["content"] == "match-1"

    combined = await client.get(
        "/api/events?event_type=agent_message&correlation_id=corr-events-match"
    )
    assert combined.status_code == 200
    combined_payload = combined.json()
    assert len(combined_payload) == 1
    assert combined_payload[0]["payload"]["content"] == "match-1"


@pytest.mark.asyncio
async def test_api_events_invalid_limit_has_structured_error(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/events?limit=invalid")
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "invalid_limit"
    assert "integer" in payload["message"]


@pytest.mark.asyncio
async def test_api_search_returns_501_when_unconfigured(web_env) -> None:
    client, *_rest = web_env
    response = await client.post("/api/search", json={"query": "auth"})
    assert response.status_code == 501
    payload = response.json()
    assert payload["error"] == "search_not_configured"
    assert "uv sync --extra search" in payload["message"]
    assert payload["docs"] == "/docs/search-setup"


@pytest.mark.asyncio
async def test_api_search_returns_503_when_backend_unavailable(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeSearchService:
        available = False

        async def search(self, query, collection, top_k, mode):  # noqa: ANN001, ANN202
            del query, collection, top_k, mode
            return []

    app = create_app(event_store, node_store, EventBus(), search_service=FakeSearchService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/search", json={"query": "auth"})

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"] == "search_backend_unavailable"
    assert "not reachable" in payload["message"].lower()
    assert payload["docs"] == "/docs/search-setup"


@pytest.mark.asyncio
async def test_api_search_requires_query(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeSearchService:
        available = True

        async def search(self, query, collection, top_k, mode):  # noqa: ANN001, ANN202
            del query, collection, top_k, mode
            return []

    app = create_app(event_store, node_store, EventBus(), search_service=FakeSearchService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/search", json={})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_search_rejects_invalid_mode(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeSearchService:
        available = True

        async def search(self, query, collection, top_k, mode):  # noqa: ANN001, ANN202
            del query, collection, top_k, mode
            return []

    app = create_app(event_store, node_store, EventBus(), search_service=FakeSearchService())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/search",
            json={"query": "auth", "mode": "invalid"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_api_search_happy_path(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeSearchService:
        available = True
        calls: list[tuple[str, str | None, int, str]] = []

        async def search(
            self,
            query: str,
            collection: str | None,
            top_k: int,
            mode: str,
        ) -> list[dict]:
            self.calls.append((query, collection, top_k, mode))
            return [{"chunk_id": "c1", "score": 0.9}]

    search_service = FakeSearchService()
    app = create_app(event_store, node_store, EventBus(), search_service=search_service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/search",
            json={"query": "auth", "collection": "code", "top_k": 5, "mode": "hybrid"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "auth"
    assert payload["collection"] == "code"
    assert payload["mode"] == "hybrid"
    assert payload["total_results"] == 1
    assert payload["results"] == [{"chunk_id": "c1", "score": 0.9}]
    assert search_service.calls == [("auth", "code", 5, "hybrid")]


@pytest.mark.asyncio
async def test_api_search_clamps_top_k(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeSearchService:
        available = True
        last_call: tuple[str, str | None, int, str] | None = None

        async def search(
            self,
            query: str,
            collection: str | None,
            top_k: int,
            mode: str,
        ) -> list[dict]:
            self.last_call = (query, collection, top_k, mode)
            return []

    search_service = FakeSearchService()
    app = create_app(event_store, node_store, EventBus(), search_service=search_service)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/search", json={"query": "auth", "top_k": 9999})
    assert response.status_code == 200
    assert search_service.last_call == ("auth", "code", 100, "hybrid")


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env
    response = await client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"] == __version__
    assert payload["nodes"] >= 1


@pytest.mark.asyncio
async def test_health_endpoint_includes_metrics(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env
    metrics = Metrics(agent_turns_total=2, events_emitted_total=3)
    app = create_app(event_store, node_store, EventBus(), metrics=metrics)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["metrics"]["agent_turns_total"] == 2
    assert payload["metrics"]["events_emitted_total"] == 3


@pytest.mark.asyncio
async def test_health_endpoint_uses_count_query_not_list_nodes(web_env, monkeypatch) -> None:
    client, node_store, _event_store, _source_path = web_env

    async def fail_list_nodes(*_args, **_kwargs):  # noqa: ANN202
        raise AssertionError("health endpoint should use COUNT(*) query")

    monkeypatch.setattr(node_store, "list_nodes", fail_list_nodes)

    response = await client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["nodes"] >= 1


@pytest.mark.asyncio
async def test_api_cursor_resolves_node(web_env) -> None:
    client, _node_store, _event_store, source_path = web_env
    response = await client.post(
        "/api/cursor",
        json={
            "file_path": str(source_path),
            "line": 1,
            "character": 0,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["node_id"] == "src/app.py::a"


@pytest.mark.asyncio
async def test_api_cursor_requires_file_path(web_env) -> None:
    client, *_rest = web_env
    response = await client.post(
        "/api/cursor",
        json={"line": 1, "character": 0},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_sse_stream_connected(web_env) -> None:
    client, _node_store, _event_store, _source_path = web_env

    async with client.stream("GET", "/sse?once=1") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


@pytest.mark.asyncio
async def test_sse_receives_events(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env

    async def read_one_data_line(response: httpx.Response) -> str:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                return line
        raise AssertionError("SSE stream closed before data line was received")

    await event_store.append(
        AgentMessageEvent(
            from_agent="user",
            to_agent="src/app.py::a",
            content="from-sse-test",
        )
    )
    async with client.stream("GET", "/sse?once=1&replay=5") as response:
        data_line = await asyncio.wait_for(read_one_data_line(response), timeout=2.0)

    payload = json.loads(data_line.removeprefix("data: ").strip())
    assert payload["event_type"] == "agent_message"
    assert payload["payload"]["content"] == "from-sse-test"
    assert set(payload.keys()) == {
        "event_type",
        "timestamp",
        "correlation_id",
        "tags",
        "payload",
    }


@pytest.mark.asyncio
async def test_sse_replay_and_live_payload_shapes_match(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    async def read_one_data_line(response: httpx.Response) -> str:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                return line
        raise AssertionError("SSE stream closed before data line was received")

    await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="replay-shape")
    )

    async with _client.stream("GET", "/sse?once=1&replay=1") as replay_response:
        replay_line = await asyncio.wait_for(read_one_data_line(replay_response), timeout=2.0)

    class FakeEventBus:
        @asynccontextmanager
        async def stream(self) -> AsyncIterator[AsyncIterator[AgentMessageEvent]]:
            async def iterate() -> AsyncIterator[AgentMessageEvent]:
                yield AgentMessageEvent(
                    from_agent="user",
                    to_agent="src/app.py::a",
                    content="live-shape",
                )

            yield iterate()

    app = create_app(event_store, node_store, FakeEventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream("GET", "/sse") as live_response:
            live_line = await asyncio.wait_for(read_one_data_line(live_response), timeout=2.0)

    replay_payload = json.loads(replay_line.removeprefix("data: ").strip())
    live_payload = json.loads(live_line.removeprefix("data: ").strip())
    assert set(replay_payload.keys()) == {
        "event_type",
        "timestamp",
        "correlation_id",
        "tags",
        "payload",
    }
    assert set(live_payload.keys()) == {
        "event_type",
        "timestamp",
        "correlation_id",
        "tags",
        "payload",
    }


@pytest.mark.asyncio
async def test_sse_includes_event_id(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    event_id = await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="with-id")
    )

    async with client.stream("GET", "/sse?once=1&replay=1") as response:
        lines = await asyncio.wait_for(_read_sse_event_lines(response), timeout=2.0)

    id_line = next((line for line in lines if line.startswith("id: ")), None)
    data_line = next((line for line in lines if line.startswith("data: ")), None)
    assert id_line == f"id: {event_id}"
    assert data_line is not None
    payload = json.loads(data_line.removeprefix("data: ").strip())
    assert payload["payload"]["content"] == "with-id"


@pytest.mark.asyncio
async def test_sse_last_event_id_header(web_env) -> None:
    client, _node_store, event_store, _source_path = web_env
    first_id = await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="first")
    )
    _second_id = await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="second")
    )

    async with client.stream(
        "GET",
        "/sse?once=1",
        headers={"Last-Event-ID": str(first_id)},
    ) as response:
        lines = await asyncio.wait_for(_read_sse_event_lines(response), timeout=2.0)

    id_line = next((line for line in lines if line.startswith("id: ")), None)
    data_line = next((line for line in lines if line.startswith("data: ")), None)
    assert id_line is not None
    assert data_line is not None
    payload = json.loads(data_line.removeprefix("data: ").strip())
    assert payload["payload"]["content"] == "second"


@pytest.mark.asyncio
async def test_get_events_after(web_env) -> None:
    _client, _node_store, event_store, _source_path = web_env
    first_id = await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="a")
    )
    await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="b")
    )
    await event_store.append(
        AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="c")
    )

    rows = await event_store.get_events_after(str(first_id))
    assert [row["payload"]["content"] for row in rows] == ["b", "c"]
    assert rows[0]["id"] > first_id


@pytest.mark.asyncio
async def test_sse_stream_stops_on_shutdown(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeEventBus:
        @asynccontextmanager
        async def stream(self) -> AsyncIterator[AsyncIterator[AgentMessageEvent]]:
            async def iterate() -> AsyncIterator[AgentMessageEvent]:
                while True:
                    await asyncio.sleep(1.0)
                    yield AgentMessageEvent(
                        from_agent="user",
                        to_agent="src/app.py::a",
                        content="idle",
                    )

            yield iterate()

    app = create_app(event_store, node_store, FakeEventBus())
    app.state.sse_shutdown_event.set()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with client.stream("GET", "/sse") as response:
            lines: list[str] = []
            async for line in response.aiter_lines():
                lines.append(line)
                if "server-shutdown" in line:
                    break

    assert ": server-shutdown" in lines


@pytest.mark.asyncio
async def test_app_lifespan_sets_shutdown_event(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env
    app = create_app(event_store, node_store, EventBus())
    assert not app.state.sse_shutdown_event.is_set()

    async with app.router.lifespan_context(app):
        assert not app.state.sse_shutdown_event.is_set()

    assert app.state.sse_shutdown_event.is_set()


@pytest.mark.asyncio
async def test_conversation_endpoint_returns_history(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeActor:
        @property
        def history(self) -> list[Message]:
            return [
                Message(role="user", content="hello"),
                Message(role="assistant", content="hi"),
            ]

    class FakeActorPool:
        @property
        def actors(self) -> dict[str, FakeActor]:
            return {"src/app.py::a": FakeActor()}

    app = create_app(event_store, node_store, EventBus(), actor_pool=FakeActorPool())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/nodes/src/app.py::a/conversation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "src/app.py::a"
    assert payload["history"][0]["role"] == "user"
    assert payload["history"][1]["content"] == "hi"


@pytest.mark.asyncio
async def test_conversation_endpoint_enforces_history_and_content_limits(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env

    class FakeActor:
        @property
        def history(self) -> list[Message]:
            return [
                Message(role="user", content="111111"),
                Message(role="assistant", content="222222"),
                Message(role="user", content="333333"),
                Message(role="assistant", content="444444"),
                Message(role="user", content="555555"),
            ]

    class FakeActorPool:
        @property
        def actors(self) -> dict[str, FakeActor]:
            return {"src/app.py::a": FakeActor()}

    app = create_app(
        event_store,
        node_store,
        EventBus(),
        actor_pool=FakeActorPool(),
        conversation_history_max_entries=3,
        conversation_message_max_chars=4,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/nodes/src/app.py::a/conversation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "src/app.py::a"
    assert payload["truncated"] is True
    assert payload["history_limit"] == 3
    assert len(payload["history"]) == 3
    assert [item["content"] for item in payload["history"]] == ["3333", "4444", "5555"]


@pytest.mark.asyncio
async def test_conversation_endpoint_404_no_actor(web_env) -> None:
    _client, node_store, event_store, _source_path = web_env
    app = create_app(event_store, node_store, EventBus())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/nodes/src/app.py::a/conversation")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_approve_endpoint_removed(web_env) -> None:
    client, *_rest = web_env
    response = await client.post("/api/approve", json={"id": "x"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_reject_endpoint_removed(web_env) -> None:
    client, *_rest = web_env
    response = await client.post("/api/reject", json={"id": "x"})
    assert response.status_code == 404
