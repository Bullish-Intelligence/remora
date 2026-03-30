"""Capability classes for agent tool scripts."""

from __future__ import annotations

import asyncio
import fnmatch
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.events import (
    AgentMessageEvent,
    CustomEvent,
    HumanInputRequestEvent,
    RewriteProposalEvent,
    SubscriptionPattern,
)
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.model.node import Node
from remora.core.model.types import NodeStatus, NodeType, serialize_enum
from remora.core.services.broker import HumanInputBroker
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore

if TYPE_CHECKING:
    from remora.core.storage.workspace import AgentWorkspace

_TEXT_EXTENSIONS = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".pym"}


class FileCapabilities:
    """File system operations for agent tools."""

    def __init__(
        self,
        workspace: AgentWorkspace,
        *,
        search_content_max_matches: int = 1000,
    ) -> None:
        self._workspace = workspace
        self._search_content_max_matches = max(1, int(search_content_max_matches))

    async def read_file(self, path: str) -> str:
        return await self._workspace.read(path)

    async def write_file(self, path: str, content: str) -> None:
        await self._workspace.write(path, content)

    async def list_dir(self, path: str = ".") -> list[str]:
        return await self._workspace.list_dir(path)

    async def file_exists(self, path: str) -> bool:
        return await self._workspace.exists(path)

    async def search_files(self, pattern: str) -> list[str]:
        paths = await self._workspace.list_all_paths()
        return sorted(path for path in paths if fnmatch.fnmatch(path, f"*{pattern}*"))

    async def search_content(self, pattern: str, path: str = ".") -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        paths = await self._workspace.list_all_paths()
        for file_path in paths:
            normalized = file_path.strip("/")
            if path not in {".", "/", ""} and not normalized.startswith(path.strip("/")):
                continue
            ext = Path(normalized).suffix.lower()
            if ext and ext not in _TEXT_EXTENSIONS:
                continue
            try:
                content = await self._workspace.read(normalized)
            except FileNotFoundError:
                continue
            for index, line in enumerate(content.splitlines(), start=1):
                if pattern in line:
                    matches.append({"file": normalized, "line": index, "text": line})
                    if len(matches) >= self._search_content_max_matches:
                        return matches
        return matches

    def to_dict(self) -> dict[str, Any]:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "file_exists": self.file_exists,
            "search_files": self.search_files,
            "search_content": self.search_content,
        }


class KVCapabilities:
    """Key-value store operations for agent tools."""

    def __init__(self, workspace: AgentWorkspace) -> None:
        self._workspace = workspace

    async def kv_get(self, key: str) -> Any | None:
        return await self._workspace.kv_get(key)

    async def kv_set(self, key: str, value: Any) -> None:
        await self._workspace.kv_set(key, value)

    async def kv_delete(self, key: str) -> None:
        await self._workspace.kv_delete(key)

    async def kv_list(self, prefix: str = "") -> list[str]:
        return await self._workspace.kv_list(prefix)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kv_get": self.kv_get,
            "kv_set": self.kv_set,
            "kv_delete": self.kv_delete,
            "kv_list": self.kv_list,
        }


class GraphCapabilities:
    """Graph operations for agent tools."""

    def __init__(self, node_id: str, node_store: NodeStore) -> None:
        self._node_id = node_id
        self._node_store = node_store

    async def graph_get_node(self, target_id: str) -> dict[str, Any] | None:
        node = await self._node_store.get_node(target_id)
        return node.model_dump() if node is not None else None

    async def graph_query_nodes(
        self,
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_node_type: NodeType | None = None
        normalized_role: str | None = (
            role.strip() if isinstance(role, str) and role.strip() else None
        )
        if node_type is not None:
            node_type_name = node_type.strip()
            if node_type_name:
                valid_node_types = {serialize_enum(item) for item in NodeType}
                if node_type_name in valid_node_types:
                    normalized_node_type = NodeType(node_type_name)
                elif node_type_name.startswith("NodeType."):
                    choices = ", ".join(sorted(valid_node_types))
                    raise ValueError(
                        f"Invalid node_type '{node_type}'. Expected one of: {choices}"
                    )
                elif normalized_role is None:
                    # Compatibility fallback: some bundles provide role names
                    # (for example "review-agent") in node_type filters.
                    normalized_role = node_type_name

        normalized_status: NodeStatus | None = None
        if status is not None:
            status_name = status.strip()
            valid_statuses = {serialize_enum(item) for item in NodeStatus}
            if status_name not in valid_statuses:
                choices = ", ".join(sorted(valid_statuses))
                raise ValueError(f"Invalid status '{status}'. Expected one of: {choices}")
            normalized_status = NodeStatus(status_name)

        nodes = await self._node_store.list_nodes(
            node_type=normalized_node_type,
            status=normalized_status,
            file_path=file_path,
            role=normalized_role,
        )
        return [node.model_dump() for node in nodes]

    async def graph_get_edges(self, target_id: str) -> list[dict[str, Any]]:
        edges = await self._node_store.get_edges(target_id)
        return [
            {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
            for edge in edges
        ]

    async def graph_get_children(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        target = parent_id or self._node_id
        children = await self._node_store.get_children(target)
        return [node.model_dump() for node in children]

    async def graph_set_status(self, target_id: str, new_status: str) -> bool:
        target_enum = NodeStatus(new_status.strip())
        return await self._node_store.transition_status(target_id, target_enum)

    async def graph_get_importers(self, target_id: str) -> list[str]:
        """Get node IDs that import the given node."""
        return await self._node_store.get_importers(target_id)

    async def graph_get_dependencies(self, target_id: str) -> list[str]:
        """Get node IDs that the given node imports/depends on."""
        return await self._node_store.get_dependencies(target_id)

    async def graph_get_edges_by_type(
        self,
        target_id: str,
        edge_type: str,
    ) -> list[dict[str, Any]]:
        """Get edges of a specific type for a node."""
        edges = await self._node_store.get_edges_by_type(target_id, edge_type)
        return [
            {"from_id": edge.from_id, "to_id": edge.to_id, "edge_type": edge.edge_type}
            for edge in edges
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_get_node": self.graph_get_node,
            "graph_query_nodes": self.graph_query_nodes,
            "graph_get_edges": self.graph_get_edges,
            "graph_get_children": self.graph_get_children,
            "graph_set_status": self.graph_set_status,
            "graph_get_importers": self.graph_get_importers,
            "graph_get_dependencies": self.graph_get_dependencies,
            "graph_get_edges_by_type": self.graph_get_edges_by_type,
        }


class EventCapabilities:
    """Event operations for agent tools."""

    def __init__(
        self,
        node_id: str,
        correlation_id: str | None,
        event_store: EventStore,
        emit: Callable[[Event], Awaitable[int]],
    ) -> None:
        self._node_id = node_id
        self._correlation_id = correlation_id
        self._event_store = event_store
        self._emit = emit

    async def event_emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        tags: list[str] | None = None,
    ) -> None:
        event = CustomEvent(
            event_type=event_type,
            payload=payload,
            correlation_id=self._correlation_id,
            tags=tuple(tags or ()),
        )
        await self._emit(event)

    async def event_subscribe(
        self,
        event_types: list[str] | None = None,
        from_agents: list[str] | None = None,
        path_glob: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        pattern = SubscriptionPattern(
            event_types=event_types,
            from_agents=from_agents,
            path_glob=path_glob,
            tags=tags,
        )
        return await self._event_store.subscriptions.register(self._node_id, pattern)

    async def event_unsubscribe(self, subscription_id: int) -> bool:
        return await self._event_store.subscriptions.unregister(subscription_id)

    async def event_get_history(self, target_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return await self._event_store.get_events_for_agent(target_id, limit=limit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_emit": self.event_emit,
            "event_subscribe": self.event_subscribe,
            "event_unsubscribe": self.event_unsubscribe,
            "event_get_history": self.event_get_history,
        }


class CommunicationCapabilities:
    """Inter-agent communication operations for agent tools."""

    def __init__(
        self,
        node_id: str,
        correlation_id: str | None,
        workspace: AgentWorkspace,
        node_store: NodeStore,
        event_store: EventStore,
        emit: Callable[[Event], Awaitable[int]],
        *,
        broker: HumanInputBroker | None = None,
        human_input_timeout_s: float = 300.0,
        broadcast_max_targets: int = 50,
        send_message_limiter: SlidingWindowRateLimiter | None = None,
    ) -> None:
        self._node_id = node_id
        self._correlation_id = correlation_id
        self._workspace = workspace
        self._node_store = node_store
        self._event_store = event_store
        self._broker = broker
        self._emit = emit
        self._human_input_timeout_s = human_input_timeout_s
        self._broadcast_max_targets = max(1, int(broadcast_max_targets))
        self._send_message_limiter = send_message_limiter

    async def send_message(self, to_node_id: str, content: str) -> dict[str, str | bool]:
        if not self._allow_send_message():
            return {"sent": False, "reason": "rate_limited"}
        await self._emit(
            AgentMessageEvent(
                from_agent=self._node_id,
                to_agent=to_node_id,
                content=content,
                correlation_id=self._correlation_id,
            )
        )
        return {"sent": True, "reason": "sent"}

    async def broadcast(self, pattern: str, content: str) -> str:
        nodes = await self._node_store.list_nodes()
        target_ids = _resolve_broadcast_targets(self._node_id, pattern, nodes)
        limited_targets = target_ids[: self._broadcast_max_targets]
        for target_id in limited_targets:
            await self._emit(
                AgentMessageEvent(
                    from_agent=self._node_id,
                    to_agent=target_id,
                    content=content,
                    correlation_id=self._correlation_id,
                )
            )
        return f"Broadcast sent to {len(limited_targets)} agents"

    async def request_human_input(
        self,
        question: str,
        options: list[str] | None = None,
    ) -> str:
        if self._broker is None:
            raise RuntimeError("HumanInputBroker not available")
        request_id = str(uuid.uuid4())
        future = self._broker.create_future(request_id)

        await self._node_store.transition_status(self._node_id, NodeStatus.AWAITING_INPUT)
        await self._emit(
            HumanInputRequestEvent(
                agent_id=self._node_id,
                request_id=request_id,
                question=question,
                options=tuple(options or ()),
                correlation_id=self._correlation_id,
            )
        )

        try:
            result = await asyncio.wait_for(future, timeout=self._human_input_timeout_s)
            await self._node_store.transition_status(self._node_id, NodeStatus.RUNNING)
            return result
        except TimeoutError:
            self._broker.discard(request_id)
            raise

    async def propose_changes(self, reason: str = "") -> str:
        proposal_id = str(uuid.uuid4())
        changed_files = await self._collect_changed_files()
        await self._node_store.transition_status(self._node_id, NodeStatus.AWAITING_REVIEW)
        await self._emit(
            RewriteProposalEvent(
                agent_id=self._node_id,
                proposal_id=proposal_id,
                files=tuple(changed_files),
                reason=reason,
                correlation_id=self._correlation_id,
            )
        )
        return proposal_id

    def _allow_send_message(self) -> bool:
        if self._send_message_limiter is None:
            return True
        return self._send_message_limiter.allow(self._node_id)

    async def _collect_changed_files(self) -> list[str]:
        all_paths = await self._workspace.list_all_paths()
        return sorted(path for path in all_paths if not path.startswith("_bundle/"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "send_message": self.send_message,
            "broadcast": self.broadcast,
            "request_human_input": self.request_human_input,
            "propose_changes": self.propose_changes,
        }


class SearchCapabilities:
    """Semantic search operations for agent tools."""

    def __init__(self, search_service: SearchServiceProtocol | None) -> None:
        self._search_service = search_service

    async def semantic_search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        if self._search_service is None or not self._search_service.available:
            return []
        return await self._search_service.search(query, collection, top_k, mode)

    async def find_similar_code(
        self,
        chunk_id: str,
        collection: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if self._search_service is None or not self._search_service.available:
            return []
        return await self._search_service.find_similar(chunk_id, collection, top_k)

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_search": self.semantic_search,
            "find_similar_code": self.find_similar_code,
        }


class IdentityCapabilities:
    """Agent identity and source lookup operations for agent tools."""

    def __init__(
        self,
        node_id: str,
        correlation_id: str | None,
        node_store: NodeStore,
    ) -> None:
        self._node_id = node_id
        self._correlation_id = correlation_id
        self._node_store = node_store

    async def get_node_source(self, target_id: str) -> str:
        node = await self._node_store.get_node(target_id)
        return node.text if node is not None else ""

    async def my_node_id(self) -> str:
        return self._node_id

    async def my_correlation_id(self) -> str | None:
        return self._correlation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "get_node_source": self.get_node_source,
            "my_node_id": self.my_node_id,
            "my_correlation_id": self.my_correlation_id,
        }


def _resolve_broadcast_targets(
    source_id: str,
    pattern: str,
    nodes: list[Node],
) -> list[str]:
    all_ids = [node.node_id for node in nodes if node.node_id != source_id]
    if pattern in {"*", "all"}:
        return all_ids
    if pattern == "siblings":
        source_file = ""
        for node in nodes:
            if node.node_id == source_id:
                source_file = node.file_path
                break
        return [
            node.node_id
            for node in nodes
            if node.node_id != source_id and node.file_path == source_file
        ]
    if pattern.startswith("file:"):
        file_path = pattern.split(":", maxsplit=1)[1]
        return [
            node.node_id
            for node in nodes
            if node.node_id != source_id and node.file_path == file_path
        ]
    return [node_id for node_id in all_ids if pattern in node_id]


__all__ = [
    "CommunicationCapabilities",
    "EventCapabilities",
    "FileCapabilities",
    "GraphCapabilities",
    "IdentityCapabilities",
    "KVCapabilities",
    "SearchCapabilities",
]
