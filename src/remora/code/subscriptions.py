"""Subscription wiring for discovered nodes."""

from __future__ import annotations

from remora.core.events import EventStore, SubscriptionPattern
from remora.core.model.node import Node
from remora.core.model.types import EventType, NodeType
from remora.core.storage.workspace import CairnWorkspaceService


class SubscriptionManager:
    """Wires event subscriptions for nodes based on their type and config."""

    def __init__(
        self,
        event_store: EventStore,
        workspace_service: CairnWorkspaceService,
    ):
        self._event_store = event_store
        self._workspace_service = workspace_service

    async def register_for_node(
        self,
        node: Node,
        *,
        virtual_subscriptions: tuple[SubscriptionPattern, ...] = (),
    ) -> None:
        """Register all appropriate subscriptions for a node."""
        await self._event_store.subscriptions.unregister_by_agent(node.node_id)

        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(to_agent=node.node_id),
        )

        if node.node_type == NodeType.VIRTUAL:
            for pattern in virtual_subscriptions:
                await self._event_store.subscriptions.register(node.node_id, pattern)
            return

        if node.node_type == NodeType.DIRECTORY:
            subtree_glob = "**" if node.file_path == "." else f"**/{node.file_path}/**"
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=[EventType.NODE_CHANGED],
                    path_glob=subtree_glob,
                ),
            )
            await self._event_store.subscriptions.register(
                node.node_id,
                SubscriptionPattern(
                    event_types=[EventType.CONTENT_CHANGED],
                    path_glob=subtree_glob,
                ),
            )
            return

        if self._workspace_service.has_workspace(node.node_id):
            workspace = await self._workspace_service.get_agent_workspace(node.node_id)
            self_reflect_config = await workspace.kv_get("_system/self_reflect")
            if isinstance(self_reflect_config, dict) and self_reflect_config.get("enabled"):
                await self._event_store.subscriptions.register(
                    node.node_id,
                    SubscriptionPattern(
                        event_types=[EventType.AGENT_COMPLETE],
                        from_agents=[node.node_id],
                        tags=["primary"],
                    ),
                )

        await self._event_store.subscriptions.register(
            node.node_id,
            SubscriptionPattern(
                event_types=[EventType.CONTENT_CHANGED],
                path_glob=node.file_path,
            ),
        )


__all__ = ["SubscriptionManager"]
