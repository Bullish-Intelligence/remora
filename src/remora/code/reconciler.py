"""File reconciler that keeps discovered nodes in sync with source files."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite
import yaml
from fsdantic import FileNotFoundError as FsdFileNotFoundError

from remora.code.directories import DirectoryManager
from remora.code.discovery import discover
from remora.code.languages import LanguageRegistry
from remora.code.paths import resolve_query_paths
from remora.code.relationships import (
    extract_imports,
    extract_inheritance,
    resolve_relationships,
)
from remora.code.subscriptions import SubscriptionManager
from remora.code.virtual_agents import VirtualAgentManager
from remora.code.watcher import FileWatcher
from remora.core.events import (
    ContentChangedEvent,
    EventBus,
    EventStore,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.model.config import Config, resolve_bundle_dirs, resolve_bundle_search_paths
from remora.core.model.errors import RemoraError, WorkspaceError
from remora.core.model.node import Node
from remora.core.model.types import EventType, NodeStatus
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import CairnWorkspaceService

logger = logging.getLogger(__name__)


class FileReconciler:
    """Incremental file reconciler with add/change/delete handling."""

    _MAX_FILE_LOCKS = 500

    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
        project_root: Path,
        language_registry: LanguageRegistry,
        subscription_manager: SubscriptionManager,
        *,
        search_service: SearchServiceProtocol | None = None,
        tx: Any | None = None,
    ):
        self._config = config
        self._node_store = node_store
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._project_root = project_root.resolve()
        self._language_registry = language_registry
        self._subscription_manager = subscription_manager
        self._search_service = search_service
        self._tx = tx
        self._bundle_search_paths = resolve_bundle_search_paths(config, self._project_root)
        self._query_paths = resolve_query_paths(self._config, self._project_root)
        self._file_state: dict[str, tuple[int, set[str]]] = {}
        self._name_index: dict[str, list[str]] = {}
        self._file_locks: dict[str, asyncio.Lock] = {}
        self._file_lock_generations: dict[str, int] = {}
        self._reconcile_generation = 0
        # Re-copy bundle templates once after startup so existing agent workspaces
        # pick up updated tool scripts.
        self._bundles_bootstrapped = False

        self._watcher = FileWatcher(config, project_root)

        # Subscription lifecycle state tracking
        self._event_bus: EventBus | None = None
        self._content_subscription_active: bool = False
        self._directory_manager = DirectoryManager(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root,
            remove_node=self._remove_node,
            register_subscriptions=self._subscription_manager.register_for_node,
            provision_bundle=self._provision_bundle,
        )
        self._virtual_agent_manager = VirtualAgentManager(
            config,
            node_store,
            event_store,
            remove_node=self._remove_node,
            register_subscriptions=self._subscription_manager.register_for_node,
            provision_bundle=self._provision_bundle,
        )

    async def full_scan(self) -> list[Node]:
        """Perform a full startup scan and return current graph nodes."""
        await self.reconcile_cycle()
        return await self._node_store.list_nodes()

    async def reconcile_cycle(self) -> None:
        """Run one reconciliation cycle over changed/new/deleted files."""
        generation = self._next_reconcile_generation()
        await self._virtual_agent_manager.sync()
        current_mtimes = self._watcher.collect_file_mtimes()
        sync_existing_bundles = not self._bundles_bootstrapped
        await self._directory_manager.materialize(
            set(current_mtimes.keys()),
            sync_existing_bundles=sync_existing_bundles,
        )

        changed_paths = [
            file_path
            for file_path, mtime_ns in current_mtimes.items()
            if file_path not in self._file_state or self._file_state[file_path][0] != mtime_ns
        ]
        changed_paths_sorted = sorted(changed_paths)
        deleted_paths = sorted(set(self._file_state) - set(current_mtimes))

        for file_path in changed_paths_sorted:
            await self._reconcile_file(
                file_path,
                current_mtimes[file_path],
                generation=generation,
                sync_existing_bundles=sync_existing_bundles,
                refresh_relationships=False,
            )

        for file_path in deleted_paths:
            _mtime, node_ids = self._file_state[file_path]
            for node_id in sorted(node_ids):
                await self._remove_node(node_id)
            await self._deindex_file_for_search(file_path)
            self._file_state.pop(file_path, None)

        await self._refresh_semantic_relationships_for_paths(
            set(changed_paths_sorted) | set(deleted_paths)
        )

        self._bundles_bootstrapped = True
        self._evict_stale_file_locks(generation)

    async def run_forever(self) -> None:
        """Continuously reconcile changed files using watchfiles."""
        await self._watcher.watch(self._handle_watch_changes)

    def stop(self) -> None:
        self._watcher.stop()
        # Unsubscribe from content change events if currently subscribed
        if self._event_bus is not None and self._content_subscription_active:
            self._event_bus.unsubscribe(self._on_content_changed)
            self._content_subscription_active = False
            self._event_bus = None

    @property
    def stop_task(self) -> asyncio.Task | None:
        """Expose the current stop-event task for observers."""
        return self._watcher.stop_task

    async def start(self, event_bus: EventBus) -> None:
        """Subscribe to content change events for immediate reconciliation.

        This method is idempotent - calling it multiple times with the same
        event bus will not create duplicate subscriptions.
        """
        # If already subscribed to this bus, return early
        if self._content_subscription_active and self._event_bus is event_bus:
            return

        # If subscribed to a different bus, unsubscribe first
        if self._event_bus is not None and self._content_subscription_active:
            self._event_bus.unsubscribe(self._on_content_changed)

        self._event_bus = event_bus
        event_bus.subscribe(EventType.CONTENT_CHANGED, self._on_content_changed)
        self._content_subscription_active = True

    async def _handle_watch_changes(self, changed_files: set[str]) -> None:
        """Process one watchfiles batch with isolated error handling."""
        generation = self._next_reconcile_generation()
        try:
            relationship_refresh_triggers: set[str] = set()
            for file_path in sorted(changed_files):
                path = Path(file_path)
                path_str = str(path)
                relationship_refresh_triggers.add(path_str)
                if path.exists() and path.is_file():
                    mtime = path.stat().st_mtime_ns
                    await self._reconcile_file(
                        path_str,
                        mtime,
                        generation=generation,
                        refresh_relationships=False,
                    )
                elif path_str in self._file_state:
                    _mtime, node_ids = self._file_state[path_str]
                    for node_id in sorted(node_ids):
                        await self._remove_node(node_id)
                    await self._deindex_file_for_search(path_str)
                    self._file_state.pop(path_str, None)
            await self._refresh_semantic_relationships_for_paths(relationship_refresh_triggers)
            self._evict_stale_file_locks(generation)
        # Error boundary: one failed watch batch must not stop file watching.
        except (OSError, RemoraError, aiosqlite.Error):
            logger.exception("Watch-triggered reconcile failed")

    async def _reconcile_file(
        self,
        file_path: str,
        mtime_ns: int,
        *,
        generation: int | None = None,
        sync_existing_bundles: bool = False,
        refresh_relationships: bool = True,
    ) -> None:
        lock_generation = (
            generation if generation is not None else self._next_reconcile_generation()
        )
        async with self._file_lock(file_path, lock_generation):
            await self._do_reconcile_file(
                file_path,
                mtime_ns,
                sync_existing_bundles=sync_existing_bundles,
                refresh_relationships=refresh_relationships,
            )
        if generation is None:
            self._evict_stale_file_locks(lock_generation)

    async def _do_reconcile_file(
        self,
        file_path: str,
        mtime_ns: int,
        *,
        sync_existing_bundles: bool = False,
        refresh_relationships: bool = True,
    ) -> None:
        discovered = discover(
            [Path(file_path)],
            language_map=self._config.behavior.language_map,
            language_registry=self._language_registry,
            query_paths=self._query_paths,
            ignore_patterns=self._config.project.workspace_ignore_patterns,
            languages=(
                list(self._config.project.discovery_languages)
                if self._config.project.discovery_languages
                else None
            ),
        )
        old_ids = self._file_state.get(file_path, (0, set()))[1]
        new_ids = {node.node_id for node in discovered}

        existing_nodes = await self._node_store.get_nodes_by_ids(sorted(new_ids))
        existing_by_id = {node.node_id: node for node in existing_nodes}
        old_hashes = {node.node_id: node.source_hash for node in existing_nodes}
        projected: list[Node] = []
        for node in discovered:
            existing = existing_by_id.get(node.node_id)

            if existing is not None and existing.source_hash == node.source_hash:
                if sync_existing_bundles:
                    mapped_bundle = self._config.resolve_bundle(node.node_type, node.name)
                    role = mapped_bundle or existing.role
                    await self._provision_bundle(node.node_id, role)
                projected.append(existing)
                continue

            mapped_bundle = self._config.resolve_bundle(node.node_type, node.name)
            node.status = existing.status if existing is not None else NodeStatus.IDLE
            node.role = (
                mapped_bundle
                if mapped_bundle is not None
                else (existing.role if existing is not None else None)
            )
            await self._node_store.upsert_node(node)

            if existing is None:
                await self._provision_bundle(node.node_id, mapped_bundle)

            projected.append(node)

        self._index_node_names(projected)

        if refresh_relationships:
            await self._refresh_relationships(file_path, projected_nodes=projected)

        if self._tx is not None:
            async with self._tx.batch():
                await self._reconcile_events(projected, old_ids, new_ids, old_hashes, file_path)
        else:
            await self._reconcile_events(projected, old_ids, new_ids, old_hashes, file_path)

        self._file_state[file_path] = (mtime_ns, new_ids)
        await self._index_file_for_search(file_path)

    async def _refresh_relationships(
        self,
        file_path: str,
        *,
        projected_nodes: list[Node] | None = None,
    ) -> None:
        plugin = self._python_plugin_for_path(file_path)
        if plugin is None:
            return

        file_nodes = (
            projected_nodes
            if projected_nodes is not None
            else await self._node_store.list_nodes(file_path=file_path)
        )
        file_node_ids = [node.node_id for node in file_nodes]
        nodes_by_name = {
            node.name: node.node_id for node in file_nodes if node.node_type == "class"
        }

        try:
            source_bytes = Path(file_path).read_bytes()
        except OSError:
            source_bytes = None

        if source_bytes is None:
            return

        raw_rels = extract_imports(
            source_bytes,
            plugin,
            file_path,
            file_node_ids[0] if file_node_ids else file_path,
            self._query_paths,
        )
        raw_rels.extend(
            extract_inheritance(
                source_bytes,
                plugin,
                file_path,
                nodes_by_name,
                self._query_paths,
            )
        )
        edges = resolve_relationships(raw_rels, self._name_index)
        for node_id in file_node_ids:
            await self._node_store.delete_outgoing_edges_by_type(node_id, "imports")
            await self._node_store.delete_outgoing_edges_by_type(node_id, "inherits")
        for edge in edges:
            await self._node_store.add_edge(edge.from_id, edge.to_id, edge.edge_type)

    async def _refresh_semantic_relationships_for_paths(self, changed_paths: set[str]) -> None:
        refresh_paths = self._semantic_refresh_paths(changed_paths)
        for refresh_path in refresh_paths:
            await self._refresh_relationships(refresh_path)

    def _semantic_refresh_paths(self, changed_paths: set[str]) -> list[str]:
        changed_python_paths = {
            path for path in changed_paths if self._python_plugin_for_path(path)
        }
        if not changed_python_paths:
            return sorted(changed_paths)

        known_python_paths = {
            file_path for file_path in self._file_state if self._python_plugin_for_path(file_path)
        }
        return sorted(known_python_paths | changed_python_paths)

    def _python_plugin_for_path(self, file_path: str):  # noqa: ANN202
        language_name = self._config.behavior.language_map.get(Path(file_path).suffix.lower(), "")
        plugin = self._language_registry.get_by_name(language_name)
        if plugin is None or plugin.name != "python":
            return None
        return plugin

    async def _reconcile_events(
        self,
        projected: list[Node],
        old_ids: set[str],
        new_ids: set[str],
        old_hashes: dict[str, str],
        file_path: str,
    ) -> None:
        """Handle edges, subscriptions, and events for reconciled nodes."""
        dir_node_id = self._directory_manager.directory_id_for_file(file_path)
        for node in projected:
            if node.parent_id is None:
                node.parent_id = dir_node_id
                await self._node_store.upsert_node(node)
            if node.parent_id is not None:
                await self._node_store.add_edge(node.parent_id, node.node_id, "contains")

        projected_by_id = {node.node_id: node for node in projected}

        additions = sorted(new_ids - old_ids)
        removals = sorted(old_ids - new_ids)
        updates = sorted(new_ids & old_ids)

        for node_id in additions:
            node = projected_by_id[node_id]
            await self._subscription_manager.register_for_node(node)
            await self._event_store.append(
                NodeDiscoveredEvent(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    file_path=node.file_path,
                    name=node.name,
                )
            )

        for node_id in updates:
            node = projected_by_id[node_id]
            old_hash = old_hashes.get(node_id)
            new_hash = node.source_hash
            if old_hash is not None and old_hash != new_hash:
                await self._subscription_manager.register_for_node(node)
                await self._event_store.append(
                    NodeChangedEvent(
                        node_id=node_id,
                        old_hash=old_hash,
                        new_hash=new_hash,
                        file_path=node.file_path,
                    )
                )

        for node_id in removals:
            await self._remove_node(node_id)

    async def _index_file_for_search(self, file_path: str) -> None:
        """Index a file for semantic search, logging failures without raising."""
        if self._search_service is None or not self._search_service.available:
            return
        try:
            await self._search_service.index_file(file_path)
        # Error boundary: indexing failures should not break reconcile flow.
        except (OSError, RemoraError):
            logger.debug("Search indexing failed for %s", file_path, exc_info=True)

    async def _deindex_file_for_search(self, file_path: str) -> None:
        """Remove a file from semantic search, logging failures without raising."""
        if self._search_service is None or not self._search_service.available:
            return
        try:
            await self._search_service.delete_source(file_path)
        # Error boundary: deindex failures should not break reconcile flow.
        except (OSError, RemoraError):
            logger.debug("Search deindexing failed for %s", file_path, exc_info=True)

    def _file_lock(self, file_path: str, generation: int) -> asyncio.Lock:
        lock = self._file_locks.get(file_path)
        if lock is None:
            lock = asyncio.Lock()
            self._file_locks[file_path] = lock
        self._file_lock_generations[file_path] = generation
        return lock

    def _next_reconcile_generation(self) -> int:
        self._reconcile_generation += 1
        return self._reconcile_generation

    def _evict_stale_file_locks(self, generation: int) -> None:
        stale_paths = [
            file_path
            for file_path, lock_generation in self._file_lock_generations.items()
            if lock_generation < generation
            and file_path in self._file_locks
            and not self._file_locks[file_path].locked()
        ]
        for file_path in stale_paths:
            self._file_locks.pop(file_path, None)
            self._file_lock_generations.pop(file_path, None)

        if len(self._file_locks) <= self._MAX_FILE_LOCKS:
            return

        sorted_paths = sorted(
            self._file_lock_generations.items(),
            key=lambda item: item[1],
        )
        evict_count = len(self._file_locks) - self._MAX_FILE_LOCKS
        for file_path, _generation in sorted_paths[:evict_count]:
            lock = self._file_locks.get(file_path)
            if lock is None or lock.locked():
                continue
            self._file_locks.pop(file_path, None)
            self._file_lock_generations.pop(file_path, None)

    def _index_node_names(self, nodes: list[Node]) -> None:
        """Add node names and full names to the name index."""
        for node in nodes:
            for key in (node.name, node.full_name):
                entries = self._name_index.setdefault(key, [])
                if node.node_id not in entries:
                    entries.append(node.node_id)

    def _deindex_node_names(self, node_id: str, node: Node) -> None:
        """Remove a node from the name index."""
        for key in (node.name, node.full_name):
            if key in self._name_index:
                self._name_index[key] = [
                    indexed_node_id
                    for indexed_node_id in self._name_index[key]
                    if indexed_node_id != node_id
                ]
                if not self._name_index[key]:
                    del self._name_index[key]

    async def _remove_node(self, node_id: str) -> None:
        node = await self._node_store.get_node(node_id)
        if node is None:
            await self._event_store.subscriptions.unregister_by_agent(node_id)
            return

        self._deindex_node_names(node_id, node)
        await self._event_store.subscriptions.unregister_by_agent(node_id)
        await self._node_store.delete_node(node_id)
        await self._event_store.append(
            NodeRemovedEvent(
                node_id=node.node_id,
                node_type=node.node_type,
                file_path=node.file_path,
                name=node.name,
            )
        )

    def _resolve_bundle_template_dirs(self, bundle_name: str) -> list[Path]:
        """Resolve a bundle name to template directories using search path."""
        return resolve_bundle_dirs(bundle_name, self._bundle_search_paths)

    async def _provision_bundle(self, node_id: str, role: str | None) -> None:
        template_dirs = self._resolve_bundle_template_dirs("system")
        if role:
            template_dirs.extend(self._resolve_bundle_template_dirs(role))
        await self._workspace_service.provision_bundle(node_id, template_dirs)

        workspace = await self._workspace_service.get_agent_workspace(node_id)
        try:
            try:
                text = await workspace.read("_bundle/bundle.yaml")
            except (FileNotFoundError, FsdFileNotFoundError) as exc:
                raise WorkspaceError(
                    f"Missing bundle metadata for node '{node_id}': {exc}"
                ) from exc
            loaded = yaml.safe_load(text) or {}
            self_reflect = loaded.get("self_reflect") if isinstance(loaded, dict) else None
            if isinstance(self_reflect, dict) and self_reflect.get("enabled"):
                await workspace.kv_set("_system/self_reflect", self_reflect)
            else:
                await workspace.kv_set("_system/self_reflect", None)
        # Error boundary: bundle metadata sync is best-effort during provisioning.
        except (OSError, WorkspaceError, yaml.YAMLError):
            logger.debug("Failed to sync self_reflect config for %s", node_id, exc_info=True)

    async def _on_content_changed(self, event: ContentChangedEvent) -> None:
        """Immediately reconcile a file reported changed by upstream systems."""
        file_path = event.path
        path = Path(file_path)
        resolved = path.resolve()
        discovery_roots = [
            (
                Path(discovery_path)
                if Path(discovery_path).is_absolute()
                else self._project_root / discovery_path
            ).resolve()
            for discovery_path in self._config.project.discovery_paths
        ]
        if not any(resolved == root or root in resolved.parents for root in discovery_roots):
            return
        if path.exists() and path.is_file():
            try:
                mtime = path.stat().st_mtime_ns
                generation = self._next_reconcile_generation()
                path_str = str(path)
                await self._reconcile_file(
                    path_str,
                    mtime,
                    generation=generation,
                    refresh_relationships=False,
                )
                await self._refresh_semantic_relationships_for_paths({path_str})
                self._evict_stale_file_locks(generation)
            # Error boundary: event-triggered reconcile failures are isolated per event.
            except (OSError, RemoraError, aiosqlite.Error):
                logger.exception("Event-triggered reconcile failed for %s", file_path)


__all__ = ["FileReconciler"]
