"""Turn context for agent tool scripts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from remora.core.services.broker import HumanInputBroker
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.core.services.search import SearchServiceProtocol
from remora.core.tools.capabilities import (
    CommunicationCapabilities,
    EventCapabilities,
    FileCapabilities,
    GraphCapabilities,
    IdentityCapabilities,
    KVCapabilities,
    SearchCapabilities,
)

if TYPE_CHECKING:
    from remora.core.agents.outbox import Outbox
    from remora.core.events.store import EventStore
    from remora.core.storage.graph import NodeStore
    from remora.core.storage.workspace import AgentWorkspace


EXTERNALS_VERSION = 3


class TurnContext:
    """Per-turn context that composes grouped externals capabilities."""

    def __init__(
        self,
        node_id: str,
        workspace: AgentWorkspace,
        correlation_id: str | None,
        node_store: NodeStore,
        event_store: EventStore,
        outbox: Outbox,
        human_input_timeout_s: float = 300.0,
        search_content_max_matches: int = 1000,
        broadcast_max_targets: int = 50,
        send_message_limiter: SlidingWindowRateLimiter | None = None,
        search_service: SearchServiceProtocol | None = None,
        broker: HumanInputBroker | None = None,
    ) -> None:
        self.node_id = node_id
        self.workspace = workspace
        self.correlation_id = correlation_id
        self._outbox = outbox

        self.files = FileCapabilities(
            workspace,
            search_content_max_matches=search_content_max_matches,
        )
        self.kv = KVCapabilities(workspace)
        self.graph = GraphCapabilities(node_id, node_store)
        self.events = EventCapabilities(
            node_id,
            correlation_id,
            event_store,
            self._emit,
        )
        self.comms = CommunicationCapabilities(
            node_id,
            correlation_id,
            workspace,
            node_store,
            event_store,
            self._emit,
            broker=broker,
            human_input_timeout_s=human_input_timeout_s,
            broadcast_max_targets=broadcast_max_targets,
            send_message_limiter=send_message_limiter,
        )
        self.search = SearchCapabilities(search_service)
        self.identity = IdentityCapabilities(node_id, correlation_id, node_store)

    async def _emit(self, event: Any) -> int:
        return await self._outbox.emit(event)

    def to_capabilities_dict(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}
        capabilities.update(self.files.to_dict())
        capabilities.update(self.kv.to_dict())
        capabilities.update(self.graph.to_dict())
        capabilities.update(self.events.to_dict())
        capabilities.update(self.comms.to_dict())
        capabilities.update(self.search.to_dict())
        capabilities.update(self.identity.to_dict())
        return capabilities


__all__ = [
    "EXTERNALS_VERSION",
    "TurnContext",
]
