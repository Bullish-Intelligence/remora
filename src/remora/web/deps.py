"""Shared dependency objects for web handlers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.requests import Request

from remora.core.events.bus import EventBus
from remora.core.events.store import EventStore
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore

if TYPE_CHECKING:
    from remora.core.agents.runner import ActorPool
    from remora.core.storage.workspace import CairnWorkspaceService


_MAX_CHAT_LIMITERS = 1000


@dataclass
class WebDeps:
    """Shared dependencies for all web handlers."""

    event_store: EventStore
    node_store: NodeStore
    event_bus: EventBus
    human_input_broker: HumanInputBroker
    metrics: Metrics | None
    actor_pool: ActorPool | None
    workspace_service: CairnWorkspaceService | None
    search_service: SearchServiceProtocol | None
    shutdown_event: asyncio.Event
    chat_limiters: dict[str, SlidingWindowRateLimiter]
    chat_message_max_chars: int
    conversation_history_max_entries: int
    conversation_message_max_chars: int


def _deps_from_request(request: Request) -> WebDeps:
    return request.app.state.deps


def _get_chat_limiter(request: Request, deps: WebDeps) -> SlidingWindowRateLimiter:
    ip = request.client.host if request.client is not None else "unknown"
    limiter = deps.chat_limiters.get(ip)
    if limiter is None:
        if len(deps.chat_limiters) >= _MAX_CHAT_LIMITERS:
            oldest_key = next(iter(deps.chat_limiters))
            del deps.chat_limiters[oldest_key]
        limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60.0)
        deps.chat_limiters[ip] = limiter
    return limiter


__all__ = ["WebDeps", "_deps_from_request", "_get_chat_limiter"]
