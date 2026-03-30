"""Health check route."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora import __version__
from remora.web.deps import _deps_from_request


async def api_health(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_count = await deps.node_store.count_nodes()
    health: dict[str, object] = {
        "status": "ok",
        "version": __version__,
        "nodes": node_count,
    }
    if deps.metrics is not None:
        health["metrics"] = deps.metrics.snapshot()
    return JSONResponse(health)


def routes() -> list[Route]:
    return [Route("/api/health", endpoint=api_health)]


__all__ = ["api_health", "routes"]
