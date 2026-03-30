"""Semantic search route."""

from __future__ import annotations

import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.web.deps import _deps_from_request
from remora.web.routes._errors import error_response


async def api_search(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.search_service is None:
        return error_response(
            error="search_not_configured",
            message=(
                "Semantic search is not configured. "
                "Install with: uv sync --extra search"
            ),
            docs="/docs/search-setup",
            status_code=501,
        )
    if not deps.search_service.available:
        return error_response(
            error="search_backend_unavailable",
            message="Search backend is not reachable. Check embeddy connection.",
            docs="/docs/search-setup",
            status_code=503,
        )

    data = await request.json()
    query = str(data.get("query", "")).strip()
    if not query:
        return error_response(
            error="invalid_request",
            message="query is required",
            status_code=400,
        )

    collection = data.get("collection") or "code"
    try:
        top_k = min(100, max(1, int(data.get("top_k", 10))))
    except (TypeError, ValueError):
        return error_response(
            error="invalid_request",
            message="top_k must be an integer",
            status_code=400,
        )

    mode = str(data.get("mode", "hybrid"))
    if mode not in {"vector", "fulltext", "hybrid"}:
        return error_response(
            error="invalid_request",
            message="mode must be vector, fulltext, or hybrid",
            status_code=400,
        )

    start = time.perf_counter()
    results = await deps.search_service.search(query, collection, top_k, mode)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return JSONResponse(
        {
            "results": results,
            "query": query,
            "collection": collection,
            "mode": mode,
            "total_results": len(results),
            "elapsed_ms": round(elapsed_ms, 1),
        }
    )


def routes() -> list[Route]:
    return [Route("/api/search", endpoint=api_search, methods=["POST"])]


__all__ = ["api_search", "routes"]
