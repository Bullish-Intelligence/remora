"""Node-centric web routes."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.web.deps import _deps_from_request
from fsdantic import FileNotFoundError as FsdFileNotFoundError


async def api_nodes(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    nodes = await deps.node_store.list_nodes()
    return JSONResponse([node.model_dump() for node in nodes])


async def api_node(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(node.model_dump())


async def api_node_companion(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)

    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    companion_data: dict[str, Any] = {}
    for key in ("companion/chat_index", "companion/reflections", "companion/links"):
        value = await workspace.kv_get(key)
        if value is not None:
            short_key = key.removeprefix("companion/")
            companion_data[short_key] = value
    return JSONResponse(companion_data)


async def api_edges(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    edges = await deps.node_store.get_edges(node_id)
    payload = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
        for edge in edges
    ]
    return JSONResponse(payload)


async def api_all_edges(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    edges = await deps.node_store.list_all_edges()
    payload = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
        for edge in edges
    ]
    return JSONResponse(payload)


async def api_node_relationships(request: Request) -> JSONResponse:
    """Get cross-file relationships for a node, optionally filtered by type."""
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    edge_type = request.query_params.get("type")

    if edge_type:
        edges = await deps.node_store.get_edges_by_type(node_id, edge_type)
    else:
        all_edges = await deps.node_store.get_edges(node_id)
        edges = [edge for edge in all_edges if edge.edge_type != "contains"]

    payload = [
        {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
        for edge in edges
    ]
    return JSONResponse(payload)


async def api_conversation(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.actor_pool is None:
        return JSONResponse({"error": "No active actor for this node"}, status_code=404)

    node_id = request.path_params["node_id"]
    actor = deps.actor_pool.actors.get(node_id)
    if actor is None:
        return JSONResponse({"error": "No active actor for this node"}, status_code=404)
    history_limit = deps.conversation_history_max_entries
    message_limit = deps.conversation_message_max_chars
    full_history = actor.history
    clipped_history = full_history[-history_limit:]
    history = [
        {
            "role": str(getattr(message, "role", "")),
            "content": str(getattr(message, "content", ""))[:message_limit],
        }
        for message in clipped_history
    ]
    return JSONResponse(
        {
            "node_id": node_id,
            "history": history,
            "truncated": len(full_history) > history_limit,
            "history_limit": history_limit,
        }
    )


async def api_workspace_files(request: Request) -> JSONResponse:
    """List all file paths in a node's Cairn workspace."""
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)
    node_id = request.path_params["node_id"]
    if not deps.workspace_service.has_workspace(node_id):
        return JSONResponse({"error": "No workspace for this node"}, status_code=404)
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    paths = await workspace.list_all_paths()
    return JSONResponse({"node_id": node_id, "files": paths})


async def api_workspace_file_content(request: Request) -> JSONResponse:
    """Read a single file from a node's Cairn workspace."""
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)
    node_id = request.path_params["node_id"]
    file_path = request.path_params["file_path"]
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    try:
        content = await workspace.read(file_path)
    except (FileNotFoundError, FsdFileNotFoundError):
        return JSONResponse({"error": f"File not found: {file_path}"}, status_code=404)
    return JSONResponse({"path": file_path, "content": content})


async def api_workspace_kv(request: Request) -> JSONResponse:
    """Dump all KV entries from a node's Cairn workspace."""
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "No workspace service"}, status_code=503)
    node_id = request.path_params["node_id"]
    if not deps.workspace_service.has_workspace(node_id):
        return JSONResponse({"error": "No workspace for this node"}, status_code=404)
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    keys = await workspace.kv_list()
    entries: dict[str, Any] = {}
    for key in keys:
        entries[key] = await workspace.kv_get(key)
    return JSONResponse({"node_id": node_id, "entries": entries})


def routes() -> list[Route]:
    return [
        Route("/api/nodes", endpoint=api_nodes),
        Route("/api/edges", endpoint=api_all_edges),
        Route("/api/nodes/{node_id:path}/edges", endpoint=api_edges),
        Route("/api/nodes/{node_id:path}/relationships", endpoint=api_node_relationships),
        Route("/api/nodes/{node_id:path}/conversation", endpoint=api_conversation),
        Route("/api/nodes/{node_id:path}/companion", endpoint=api_node_companion),
        Route("/api/nodes/{node_id:path}/workspace/files/{file_path:path}", endpoint=api_workspace_file_content),
        Route("/api/nodes/{node_id:path}/workspace/files", endpoint=api_workspace_files),
        Route("/api/nodes/{node_id:path}/workspace/kv", endpoint=api_workspace_kv),
        Route("/api/nodes/{node_id:path}", endpoint=api_node),
    ]


__all__ = [
    "api_all_edges",
    "api_conversation",
    "api_edges",
    "api_node",
    "api_node_companion",
    "api_node_relationships",
    "api_nodes",
    "api_workspace_file_content",
    "api_workspace_files",
    "api_workspace_kv",
    "routes",
]
