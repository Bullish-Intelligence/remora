"""Virtual agent materialization and subscription sync."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable

from remora.core.model.config import Config, VirtualAgentConfig
from remora.core.events import (
    EventStore,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    SubscriptionPattern,
)
from remora.core.storage.graph import NodeStore
from remora.core.model.node import Node
from remora.core.model.types import NodeType


class RegisterSubscriptionsFn:
    """Protocol for subscription registration callbacks."""

    async def __call__(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None: ...


class VirtualAgentManager:
    """Keeps declarative virtual agents synchronized in the node graph."""

    def __init__(
        self,
        config: Config,
        node_store: NodeStore,
        event_store: EventStore,
        *,
        remove_node: Callable[[str], Awaitable[None]],
        register_subscriptions: RegisterSubscriptionsFn,
        provision_bundle: Callable[[str, str | None], Awaitable[None]],
    ) -> None:
        self._config = config
        self._node_store = node_store
        self._event_store = event_store
        self._remove_node = remove_node
        self._register_subscriptions = register_subscriptions
        self._provision_bundle = provision_bundle

    async def sync(self) -> None:
        """Materialize configured virtual agents into nodes + subscriptions."""
        specs = sorted(self._config.virtual_agents, key=lambda item: item.id)
        existing = await self._node_store.list_nodes(node_type=NodeType.VIRTUAL)
        existing_by_id = {node.node_id: node for node in existing}
        desired_ids = {item.id for item in specs}

        async with self._node_store.batch():
            async with self._event_store.batch():
                stale_ids = sorted(set(existing_by_id) - desired_ids)
                for node_id in stale_ids:
                    await self._remove_node(node_id)

                for spec in specs:
                    existing_node = existing_by_id.get(spec.id)
                    source_hash = self.build_hash(spec)
                    virtual_node = Node(
                        node_id=spec.id,
                        node_type=NodeType.VIRTUAL,
                        name=spec.id,
                        full_name=spec.id,
                        file_path="",
                        start_line=0,
                        end_line=0,
                        start_byte=0,
                        end_byte=0,
                        text="",
                        source_hash=source_hash,
                        parent_id=None,
                        status=existing_node.status if existing_node is not None else "idle",
                        role=spec.role,
                    )
                    patterns = self.build_patterns(spec)

                    if existing_node is None:
                        await self._node_store.upsert_node(virtual_node)
                        await self._register_subscriptions(
                            virtual_node,
                            virtual_subscriptions=patterns,
                        )
                        await self._provision_bundle(virtual_node.node_id, virtual_node.role)
                        await self._event_store.append(
                            NodeDiscoveredEvent(
                                node_id=virtual_node.node_id,
                                node_type=virtual_node.node_type,
                                file_path=virtual_node.file_path,
                                name=virtual_node.name,
                            )
                        )
                        continue

                    metadata_changed = (
                        existing_node.name != virtual_node.name
                        or existing_node.full_name != virtual_node.full_name
                        or existing_node.file_path != virtual_node.file_path
                        or existing_node.parent_id != virtual_node.parent_id
                        or existing_node.role != virtual_node.role
                    )
                    hash_changed = existing_node.source_hash != virtual_node.source_hash
                    if metadata_changed or hash_changed:
                        await self._node_store.upsert_node(virtual_node)
                    await self._register_subscriptions(
                        virtual_node,
                        virtual_subscriptions=patterns,
                    )
                    await self._provision_bundle(virtual_node.node_id, virtual_node.role)
                    if hash_changed:
                        await self._event_store.append(
                            NodeChangedEvent(
                                node_id=virtual_node.node_id,
                                old_hash=existing_node.source_hash,
                                new_hash=virtual_node.source_hash,
                            )
                        )

    @staticmethod
    def build_patterns(spec: VirtualAgentConfig) -> tuple[SubscriptionPattern, ...]:
        """Build subscription registry patterns from declarative config."""
        return tuple(
            SubscriptionPattern(
                event_types=list(item.event_types) if item.event_types else None,
                from_agents=list(item.from_agents) if item.from_agents else None,
                to_agent=item.to_agent,
                path_glob=item.path_glob,
                tags=list(item.tags) if item.tags else None,
            )
            for item in spec.subscriptions
        )

    @staticmethod
    def build_hash(spec: VirtualAgentConfig) -> str:
        """Hash virtual-agent identity-relevant config for change detection."""
        payload = {
            "role": spec.role,
            "subscriptions": [
                {
                    "event_types": list(item.event_types) if item.event_types else None,
                    "from_agents": list(item.from_agents) if item.from_agents else None,
                    "to_agent": item.to_agent,
                    "path_glob": item.path_glob,
                    "tags": list(item.tags) if item.tags else None,
                }
                for item in spec.subscriptions
            ],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["VirtualAgentManager"]
