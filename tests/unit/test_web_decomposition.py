from __future__ import annotations

import asyncio
from types import SimpleNamespace

from remora.core.services.broker import HumanInputBroker
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.web.deps import _MAX_CHAT_LIMITERS, WebDeps, _get_chat_limiter
from remora.web.routes import chat, cursor, events, health, nodes, proposals, search


def _paths(module) -> set[str]:  # noqa: ANN001
    return {route.path for route in module.routes()}


def test_route_modules_expose_expected_paths() -> None:
    assert "/api/nodes" in _paths(nodes)
    assert "/api/nodes/{node_id:path}" in _paths(nodes)
    assert "/api/edges" in _paths(nodes)
    assert "/api/nodes/{node_id:path}/relationships" in _paths(nodes)
    assert "/api/chat" in _paths(chat)
    assert "/api/nodes/{node_id:path}/respond" in _paths(chat)
    assert "/api/events" in _paths(events)
    assert "/sse" in _paths(events)
    assert "/api/proposals" in _paths(proposals)
    assert "/api/proposals/{node_id:path}/accept" in _paths(proposals)
    assert "/api/search" in _paths(search)
    assert "/api/health" in _paths(health)
    assert "/api/cursor" in _paths(cursor)


def test_get_chat_limiter_reuses_per_ip() -> None:
    deps = WebDeps(
        event_store=SimpleNamespace(),
        node_store=SimpleNamespace(),
        event_bus=SimpleNamespace(),
        human_input_broker=HumanInputBroker(),
        metrics=None,
        actor_pool=None,
        workspace_service=None,
        search_service=None,
        shutdown_event=asyncio.Event(),
        chat_limiters={},
        chat_message_max_chars=4000,
        conversation_history_max_entries=200,
        conversation_message_max_chars=2000,
    )
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    first = _get_chat_limiter(request, deps)
    second = _get_chat_limiter(request, deps)

    assert first is second


def test_chat_limiter_evicts_oldest_when_capacity_reached() -> None:
    deps = WebDeps(
        event_store=SimpleNamespace(),
        node_store=SimpleNamespace(),
        event_bus=SimpleNamespace(),
        human_input_broker=HumanInputBroker(),
        metrics=None,
        actor_pool=None,
        workspace_service=None,
        search_service=None,
        shutdown_event=asyncio.Event(),
        chat_limiters={},
        chat_message_max_chars=4000,
        conversation_history_max_entries=200,
        conversation_message_max_chars=2000,
    )
    for i in range(_MAX_CHAT_LIMITERS):
        deps.chat_limiters[f"ip-{i}"] = SlidingWindowRateLimiter(10, 60.0)

    _get_chat_limiter(SimpleNamespace(client=SimpleNamespace(host="new-ip")), deps)

    assert len(deps.chat_limiters) == _MAX_CHAT_LIMITERS
    assert "ip-0" not in deps.chat_limiters
    assert "new-ip" in deps.chat_limiters
