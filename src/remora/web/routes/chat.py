"""Chat and human-response routes."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.core.events import AgentMessageEvent, HumanInputResponseEvent
from remora.web.deps import _deps_from_request, _get_chat_limiter
from remora.web.routes._errors import error_response


async def api_chat(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if not _get_chat_limiter(request, deps).allow():
        return error_response(
            error="rate_limit_exceeded",
            message="Rate limit exceeded. Try again later.",
            status_code=429,
        )

    data = await request.json()
    node_id = str(data.get("node_id", "")).strip()
    message = str(data.get("message", "")).strip()
    if not node_id or not message:
        return error_response(
            error="invalid_request",
            message="node_id and message are required",
            status_code=400,
        )
    max_chars = deps.chat_message_max_chars
    if len(message) > max_chars:
        return error_response(
            error="message_too_long",
            message="message exceeds max length",
            status_code=413,
            extras={"max_chars": max_chars, "received_chars": len(message)},
        )

    node = await deps.node_store.get_node(node_id)
    if node is None:
        return error_response(
            error="not_found",
            message="node not found",
            status_code=404,
        )

    await deps.event_store.append(
        AgentMessageEvent(from_agent="user", to_agent=node_id, content=message)
    )
    return JSONResponse({"status": "sent"})


async def api_respond(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    data = await request.json()
    request_id = str(data.get("request_id", "")).strip()
    response_text = str(data.get("response", "")).strip()
    if not request_id or not response_text:
        return error_response(
            error="invalid_request",
            message="request_id and response required",
            status_code=400,
        )

    node_id = request.path_params["node_id"]
    resolved = deps.human_input_broker.resolve(request_id, response_text)
    if not resolved:
        return error_response(
            error="not_found",
            message="no pending request",
            status_code=404,
        )

    await deps.event_store.append(
        HumanInputResponseEvent(
            agent_id=node_id,
            request_id=request_id,
            response=response_text,
        )
    )
    return JSONResponse({"status": "ok"})


def routes() -> list[Route]:
    return [
        Route("/api/chat", endpoint=api_chat, methods=["POST"]),
        Route("/api/nodes/{node_id:path}/respond", endpoint=api_respond, methods=["POST"]),
    ]


__all__ = ["api_chat", "api_respond", "routes"]
