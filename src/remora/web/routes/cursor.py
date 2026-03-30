"""Cursor focus routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.core.events import CursorFocusEvent
from remora.core.model.types import serialize_enum
from remora.web.deps import _deps_from_request


async def api_cursor(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    data = await request.json()
    file_path = str(data.get("file_path", "")).strip()
    line_raw = data.get("line", 0)
    character_raw = data.get("character", 0)

    try:
        line = int(line_raw)
        character = int(character_raw)
    except (TypeError, ValueError):
        return JSONResponse({"error": "line and character must be integers"}, status_code=400)

    if not file_path:
        return JSONResponse({"error": "file_path is required"}, status_code=400)

    nodes = await deps.node_store.list_nodes(file_path=file_path)
    containing = [node for node in nodes if node.start_line <= line <= node.end_line]
    focused = (
        min(containing, key=lambda node: node.end_line - node.start_line) if containing else None
    )

    await deps.event_bus.emit(
        CursorFocusEvent(
            file_path=file_path,
            line=line,
            character=character,
            node_id=focused.node_id if focused else None,
            node_name=focused.full_name if focused else None,
            node_type=serialize_enum(focused.node_type) if focused is not None else None,
        )
    )
    return JSONResponse({"status": "ok", "node_id": focused.node_id if focused else None})


def routes() -> list[Route]:
    return [Route("/api/cursor", endpoint=api_cursor, methods=["POST"])]


__all__ = ["api_cursor", "routes"]
