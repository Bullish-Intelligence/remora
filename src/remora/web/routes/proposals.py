"""Rewrite proposal workflow routes."""

from __future__ import annotations

import hashlib

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from remora.core.events import ContentChangedEvent, RewriteAcceptedEvent, RewriteRejectedEvent
from remora.core.model.types import ChangeType, NodeStatus
from remora.web.deps import _deps_from_request
from remora.web.paths import _latest_rewrite_proposal, _workspace_path_to_disk_path


async def api_proposals(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    pending = await deps.node_store.list_nodes(status=NodeStatus.AWAITING_REVIEW)
    payload: list[dict[str, object]] = []
    for node in pending:
        proposal_event = await _latest_rewrite_proposal(node.node_id, deps.event_store)
        event_payload = proposal_event.get("payload", {}) if proposal_event else {}
        payload.append(
            {
                "node_id": node.node_id,
                "status": str(node.status),
                "proposal_id": event_payload.get("proposal_id", ""),
                "reason": event_payload.get("reason", ""),
                "files": event_payload.get("files", []),
            }
        )
    return JSONResponse(payload)


async def api_proposal_diff(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "workspace service unavailable"}, status_code=503)

    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    proposal_event = await _latest_rewrite_proposal(node_id, deps.event_store)
    if proposal_event is None:
        return JSONResponse({"error": "no proposal found"}, status_code=404)

    proposal_payload = proposal_event.get("payload", {})
    files = proposal_payload.get("files", [])
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    diffs: list[dict[str, str]] = []
    for workspace_path in files:
        if not isinstance(workspace_path, str):
            continue
        try:
            new_source = await workspace.read(workspace_path)
        except FileNotFoundError:
            continue

        try:
            disk_path = _workspace_path_to_disk_path(
                node.node_id,
                node.file_path,
                workspace_path,
                deps.workspace_service.project_root,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        old_source = disk_path.read_text(encoding="utf-8") if disk_path.exists() else ""
        diffs.append(
            {
                "workspace_path": workspace_path,
                "file": str(disk_path),
                "old": old_source,
                "new": new_source,
            }
        )

    return JSONResponse(
        {
            "node_id": node_id,
            "proposal_id": proposal_payload.get("proposal_id", ""),
            "reason": proposal_payload.get("reason", ""),
            "diffs": diffs,
        }
    )


async def api_proposal_accept(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    if deps.workspace_service is None:
        return JSONResponse({"error": "workspace service unavailable"}, status_code=503)

    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    proposal_event = await _latest_rewrite_proposal(node_id, deps.event_store)
    if proposal_event is None:
        return JSONResponse({"error": "no proposal found"}, status_code=404)

    proposal_payload = proposal_event.get("payload", {})
    proposal_id = str(proposal_payload.get("proposal_id", "")).strip()
    files = proposal_payload.get("files", [])
    workspace = await deps.workspace_service.get_agent_workspace(node_id)
    materialized: list[str] = []
    pending_content_changes: list[tuple[str, str, str]] = []

    for workspace_path in files:
        if not isinstance(workspace_path, str):
            continue
        try:
            new_source = await workspace.read(workspace_path)
        except FileNotFoundError:
            continue

        try:
            disk_path = _workspace_path_to_disk_path(
                node.node_id,
                node.file_path,
                workspace_path,
                deps.workspace_service.project_root,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        old_bytes = disk_path.read_bytes() if disk_path.exists() else b""
        new_bytes = new_source.encode("utf-8")
        if old_bytes == new_bytes:
            continue

        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(new_bytes)
        pending_content_changes.append(
            (
                str(disk_path),
                hashlib.sha256(old_bytes).hexdigest(),
                hashlib.sha256(new_bytes).hexdigest(),
            )
        )
        materialized.append(str(disk_path))

    await deps.node_store.transition_status(node_id, NodeStatus.IDLE)
    await deps.event_store.append(
        RewriteAcceptedEvent(
            agent_id=node_id,
            proposal_id=proposal_id,
        )
    )
    for disk_path, old_hash, new_hash in pending_content_changes:
        await deps.event_store.append(
            ContentChangedEvent(
                path=disk_path,
                change_type=ChangeType.MODIFIED,
                agent_id=node_id,
                old_hash=old_hash,
                new_hash=new_hash,
            )
        )
    return JSONResponse(
        {
            "status": "accepted",
            "proposal_id": proposal_id,
            "files": materialized,
        }
    )


async def api_proposal_reject(request: Request) -> JSONResponse:
    deps = _deps_from_request(request)
    node_id = request.path_params["node_id"]
    node = await deps.node_store.get_node(node_id)
    if node is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    proposal_event = await _latest_rewrite_proposal(node_id, deps.event_store)
    if proposal_event is None:
        return JSONResponse({"error": "no proposal found"}, status_code=404)
    proposal_payload = proposal_event.get("payload", {})
    proposal_id = str(proposal_payload.get("proposal_id", "")).strip()

    data = await request.json()
    feedback = str(data.get("feedback", "")).strip()
    await deps.node_store.transition_status(node_id, NodeStatus.IDLE)
    await deps.event_store.append(
        RewriteRejectedEvent(
            agent_id=node_id,
            proposal_id=proposal_id,
            feedback=feedback,
        )
    )
    return JSONResponse({"status": "rejected", "proposal_id": proposal_id})


def routes() -> list[Route]:
    return [
        Route("/api/proposals", endpoint=api_proposals),
        Route("/api/proposals/{node_id:path}/diff", endpoint=api_proposal_diff),
        Route(
            "/api/proposals/{node_id:path}/accept",
            endpoint=api_proposal_accept,
            methods=["POST"],
        ),
        Route(
            "/api/proposals/{node_id:path}/reject",
            endpoint=api_proposal_reject,
            methods=["POST"],
        ),
    ]


__all__ = [
    "api_proposal_accept",
    "api_proposal_diff",
    "api_proposal_reject",
    "api_proposals",
    "routes",
]
