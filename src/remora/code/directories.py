"""Directory hierarchy projection for discovered source files."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path

from remora.core.model.config import Config
from remora.core.events.store import EventStore
from remora.core.events.types import NodeChangedEvent, NodeDiscoveredEvent
from remora.core.storage.graph import NodeStore
from remora.core.model.node import Node
from remora.core.model.types import NodeType
from remora.core.storage.workspace import CairnWorkspaceService


class DirectoryManager:
    """Maintains directory nodes derived from discovered file paths."""

    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        project_root: Path,
        *,
        remove_node: Callable[[str], Awaitable[None]],
        register_subscriptions: Callable[[Node], Awaitable[None]],
        provision_bundle: Callable[[str, str | None], Awaitable[None]],
    ) -> None:
        self._config = config
        self._node_store = node_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._project_root = project_root.resolve()
        self._remove_node = remove_node
        self._register_subscriptions = register_subscriptions
        self._provision_bundle = provision_bundle
        self._subscriptions_bootstrapped = False

    def compute_hierarchy(self, file_paths: set[str]) -> tuple[set[str], dict[str, list[str]]]:
        """Compute directory IDs and per-directory children for discovered files."""
        file_rel_paths = {self._relative_file_path(path) for path in file_paths}
        dir_paths: set[str] = {"."}

        for rel_file_path in file_rel_paths:
            current = Path(rel_file_path).parent
            while True:
                dir_id = self._normalize_dir_id(current)
                dir_paths.add(dir_id)
                if dir_id == "." or current == current.parent:
                    break
                current = current.parent

        children_by_dir: dict[str, list[str]] = {dir_id: [] for dir_id in dir_paths}
        for dir_id in dir_paths:
            if dir_id == ".":
                continue
            parent_id = self._parent_dir_id(dir_id)
            children_by_dir.setdefault(parent_id, []).append(dir_id)
        for rel_file_path in file_rel_paths:
            parent_id = self._parent_dir_id(rel_file_path)
            children_by_dir.setdefault(parent_id, []).append(rel_file_path)
        return dir_paths, children_by_dir

    async def materialize(
        self,
        file_paths: set[str],
        *,
        sync_existing_bundles: bool,
    ) -> None:
        """Derive directory nodes from the set of discovered file paths."""
        dir_paths, children_by_dir = self.compute_hierarchy(file_paths)
        existing_dirs = await self._node_store.list_nodes(node_type=NodeType.DIRECTORY)
        existing_by_id = {node.node_id: node for node in existing_dirs}

        async with self._node_store.batch():
            async with self._event_store.batch():
                await self._remove_stale_directories(existing_by_id, dir_paths)
                for dir_id in sorted(dir_paths):
                    children = sorted(children_by_dir.get(dir_id, []))
                    existing = existing_by_id.get(dir_id)
                    await self._upsert_directory_node(
                        dir_id,
                        children,
                        existing,
                        sync_existing_bundles=sync_existing_bundles,
                        refresh_subscriptions=not self._subscriptions_bootstrapped,
                    )
        self._subscriptions_bootstrapped = True

    async def _remove_stale_directories(
        self, existing_by_id: dict[str, Node], desired_ids: set[str]
    ) -> None:
        """Delete directory nodes no longer present in the desired hierarchy."""
        stale_ids = sorted(
            set(existing_by_id) - desired_ids,
            key=lambda node_id: node_id.count("/"),
            reverse=True,
        )
        for node_id in stale_ids:
            await self._remove_node(node_id)

    async def _upsert_directory_node(
        self,
        dir_id: str,
        children: list[str],
        existing: Node | None,
        *,
        sync_existing_bundles: bool,
        refresh_subscriptions: bool,
    ) -> None:
        """Create or update one directory projection node."""
        parent_id = None if dir_id == "." else self._parent_dir_id(dir_id)
        name = "." if dir_id == "." else Path(dir_id).name
        source_hash = hashlib.sha256("\n".join(children).encode("utf-8")).hexdigest()
        mapped_bundle = self._config.resolve_bundle(NodeType.DIRECTORY, name)
        refresh_bundle = sync_existing_bundles

        directory_node = Node(
            node_id=dir_id,
            node_type=NodeType.DIRECTORY,
            name=name,
            full_name=dir_id,
            file_path=dir_id,
            start_line=0,
            end_line=0,
            text="",
            source_hash=source_hash,
            parent_id=parent_id,
            status=existing.status if existing is not None else "idle",
            role=(
                mapped_bundle
                if mapped_bundle is not None
                else (existing.role if existing is not None else None)
            ),
        )

        if existing is None:
            await self._node_store.upsert_node(directory_node)
            if directory_node.parent_id is not None:
                await self._node_store.add_edge(
                    directory_node.parent_id,
                    directory_node.node_id,
                    "contains",
                )
            await self._register_subscriptions(directory_node)
            await self._provision_bundle(directory_node.node_id, directory_node.role)
            await self._event_store.append(
                NodeDiscoveredEvent(
                    node_id=directory_node.node_id,
                    node_type=directory_node.node_type,
                    file_path=directory_node.file_path,
                    name=directory_node.name,
                )
            )
            return

        metadata_changed = (
            existing.parent_id != directory_node.parent_id
            or existing.file_path != directory_node.file_path
            or existing.name != directory_node.name
            or existing.full_name != directory_node.full_name
            or existing.role != directory_node.role
        )
        hash_changed = existing.source_hash != source_hash
        if metadata_changed or hash_changed:
            await self._node_store.upsert_node(directory_node)
            if directory_node.parent_id is not None:
                await self._node_store.add_edge(
                    directory_node.parent_id,
                    directory_node.node_id,
                    "contains",
                )

        if refresh_subscriptions:
            await self._register_subscriptions(directory_node)
        if refresh_bundle:
            await self._provision_bundle(directory_node.node_id, directory_node.role)

        if hash_changed:
            await self._register_subscriptions(directory_node)
            await self._event_store.append(
                NodeChangedEvent(
                    node_id=directory_node.node_id,
                    old_hash=existing.source_hash,
                    new_hash=directory_node.source_hash,
                    file_path=directory_node.file_path,
                )
            )

    def directory_id_for_file(self, file_path: str) -> str:
        rel_file_path = self._relative_file_path(file_path)
        return self._parent_dir_id(rel_file_path)

    def _relative_file_path(self, file_path: str) -> str:
        absolute = Path(file_path).resolve()
        try:
            relative = absolute.relative_to(self._project_root)
            return relative.as_posix()
        except ValueError:
            return Path(file_path).as_posix()

    @staticmethod
    def _normalize_dir_id(path: Path | str) -> str:
        value = Path(path).as_posix()
        return "." if value in {"", "."} else value

    @staticmethod
    def _parent_dir_id(path_like: str) -> str:
        path = Path(path_like)
        parent = path.parent
        if parent == path:
            return "."
        parent_str = parent.as_posix()
        return "." if parent_str in {"", "."} else parent_str


__all__ = ["DirectoryManager"]
