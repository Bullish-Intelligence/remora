"""Event list and SSE routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.web.deps import _deps_from_request
from remora.web.routes._errors import error_response
from remora.web.sse import sse_stream


def _row_to_envelope(row: dict) -> dict:
    return {
        "event_type": row.get("event_type", ""),
        "timestamp": row.get("timestamp"),
        "correlation_id": row.get("correlation_id"),
        "tags": row.get("tags", []),
        "payload": row.get("payload", {}),
    }


async def api_events(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    raw_limit = request.query_params.get("limit", "50")
    event_type = request.query_params.get("event_type")
    correlation_id = request.query_params.get("correlation_id")
    try:
        limit = max(1, min(500, int(raw_limit)))
    except ValueError:
        return error_response(
            error="invalid_limit",
            message="limit must be an integer between 1 and 500",
            status_code=400,
        )
    rows = await deps.event_store.get_events(
        limit=limit,
        event_type=event_type.strip() if event_type and event_type.strip() else None,
        correlation_id=correlation_id.strip()
        if correlation_id and correlation_id.strip()
        else None,
    )
    return JSONResponse([_row_to_envelope(row) for row in rows])


def routes() -> list[Route]:
    return [
        Route("/api/events", endpoint=api_events),
        Route("/sse", endpoint=sse_stream),
    ]


__all__ = ["api_events", "routes"]
