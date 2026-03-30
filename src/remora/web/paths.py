"""Path resolution helpers for proposal materialization."""

from __future__ import annotations

from pathlib import Path

from remora.core.events.store import EventStore
from remora.core.model.types import EventType


def _resolve_within_project_root(
    path: Path,
    workspace_path: str,
    project_root: Path | None,
) -> Path:
    candidate = path
    if project_root is not None and not candidate.is_absolute():
        candidate = project_root / candidate
    resolved = candidate.resolve()
    if project_root is None:
        return resolved
    normalized_root = project_root.resolve()
    try:
        resolved.relative_to(normalized_root)
    except ValueError as exc:
        raise ValueError(f"Path traversal attempt: {workspace_path}") from exc
    return resolved


def _workspace_path_to_disk_path(
    node_id: str,
    node_file_path: str,
    workspace_path: str,
    project_root: Path | None,
) -> Path:
    normalized = workspace_path.strip("/")
    result = Path(node_file_path)
    if normalized.startswith("source/"):
        source_path = normalized.removeprefix("source/")
        if source_path:
            if source_path.startswith("/"):
                result = Path(source_path)
            elif source_path in {node_id, node_file_path}:
                result = Path(node_file_path)
            else:
                result = Path(source_path)
    return _resolve_within_project_root(result, workspace_path, project_root)


async def _latest_rewrite_proposal(node_id: str, event_store: EventStore) -> dict | None:
    return await event_store.get_latest_event_by_type(node_id, EventType.REWRITE_PROPOSAL)


__all__ = [
    "_latest_rewrite_proposal",
    "_resolve_within_project_root",
    "_workspace_path_to_disk_path",
]
