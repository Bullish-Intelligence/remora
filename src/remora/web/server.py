"""Starlette web server app factory for Remora."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from remora.core.events.bus import EventBus
from remora.core.events.store import EventStore
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore
from remora.web.deps import WebDeps
from remora.web.middleware import CSRFMiddleware
from remora.web.routes import chat, cursor, events, health, nodes, proposals, search

if TYPE_CHECKING:
    from remora.core.agents.runner import ActorPool
    from remora.core.storage.workspace import CairnWorkspaceService

_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML: str | None = None


def _get_index_html() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        _INDEX_HTML = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return _INDEX_HTML


async def index(_request: Request) -> HTMLResponse:
    return HTMLResponse(_get_index_html())


def _build_routes() -> list[Route]:
    return [
        Route("/", endpoint=index),
        *nodes.routes(),
        *chat.routes(),
        *proposals.routes(),
        *events.routes(),
        *search.routes(),
        *health.routes(),
        *cursor.routes(),
    ]


def _build_lifespan(shutdown_event: asyncio.Event):
    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            shutdown_event.set()

    return lifespan


def create_app(
    event_store: EventStore,
    node_store: NodeStore,
    event_bus: EventBus,
    human_input_broker: HumanInputBroker | None = None,
    metrics: Metrics | None = None,
    actor_pool: ActorPool | None = None,
    workspace_service: CairnWorkspaceService | None = None,
    search_service: SearchServiceProtocol | None = None,
    chat_message_max_chars: int = 4000,
    conversation_history_max_entries: int = 200,
    conversation_message_max_chars: int = 2000,
) -> Starlette:
    """Create Starlette app exposing graph APIs, events, and chat."""
    deps = WebDeps(
        event_store=event_store,
        node_store=node_store,
        event_bus=event_bus,
        human_input_broker=human_input_broker or HumanInputBroker(),
        metrics=metrics,
        actor_pool=actor_pool,
        workspace_service=workspace_service,
        search_service=search_service,
        shutdown_event=asyncio.Event(),
        chat_limiters={},
        chat_message_max_chars=chat_message_max_chars,
        conversation_history_max_entries=conversation_history_max_entries,
        conversation_message_max_chars=conversation_message_max_chars,
    )
    app = Starlette(routes=_build_routes(), lifespan=_build_lifespan(deps.shutdown_event))
    app.state.deps = deps
    app.state.sse_shutdown_event = deps.shutdown_event
    app.add_middleware(CSRFMiddleware)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app


__all__ = ["create_app"]
