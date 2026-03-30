"""Agent runner: actor registry and lifecycle manager."""

from __future__ import annotations

import asyncio
import logging
import time

from remora.core.agents.actor import Actor
from remora.core.events import EventStore, TriggerDispatcher
from remora.core.events.types import Event
from remora.core.model.config import Config, OverflowPolicy
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import CairnWorkspaceService

logger = logging.getLogger(__name__)


class ActorPool:
    """Actor registry and lifecycle manager for agent execution.

    Creates Actor instances lazily on first trigger and routes
    events from the dispatcher to per-agent inboxes.
    """

    def __init__(
        self,
        event_store: EventStore,
        node_store: NodeStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        dispatcher: TriggerDispatcher | None = None,
        metrics: Metrics | None = None,
        search_service: SearchServiceProtocol | None = None,
        broker: HumanInputBroker | None = None,
    ):
        self._event_store = event_store
        self._dispatcher = dispatcher or event_store.dispatcher
        self._node_store = node_store
        self._workspace_service = workspace_service
        self._config = config
        self._metrics = metrics
        self._search_service = search_service
        self._broker = broker
        self._running = False
        self._accepting_events = True
        self._semaphore = asyncio.Semaphore(config.runtime.max_concurrency)
        self._actors: dict[str, Actor] = {}

        # Set ourselves as the dispatcher's router (if dispatcher exists)
        if self._dispatcher is not None:
            self._dispatcher.router = self._route_to_actor

    def _route_to_actor(self, agent_id: str, event: Event) -> None:
        """Route an event to the target agent's inbox, creating the actor if needed.

        Handles queue overflow according to configured policy.
        """
        if not self._accepting_events:
            return
        actor = self.get_or_create_actor(agent_id)

        try:
            actor.inbox.put_nowait(event)
            self._refresh_pending_inbox_items()
        except asyncio.QueueFull:
            self._handle_inbox_overflow(actor, event, agent_id)

    def _handle_inbox_overflow(self, actor: Actor, event: Event, agent_id: str) -> None:
        """Handle queue full condition according to overflow policy."""
        policy = self._config.runtime.actor_inbox_overflow_policy
        queue_size = actor.inbox.qsize()

        if self._metrics:
            self._metrics.actor_inbox_overflow_total += 1

        logger.warning(
            "Actor inbox overflow: agent_id=%s policy=%s queue_size=%d",
            agent_id,
            policy,
            queue_size,
        )

        if policy == OverflowPolicy.DROP_OLDEST:
            try:
                dropped = actor.inbox.get_nowait()
                if dropped is not None:
                    actor.inbox.put_nowait(event)
                    if self._metrics:
                        self._metrics.actor_inbox_dropped_oldest_total += 1
                    logger.warning("Dropped oldest event from inbox: agent_id=%s", agent_id)
                else:
                    logger.warning(
                        "Inbox was unexpectedly empty during drop_oldest: agent_id=%s",
                        agent_id,
                    )
            except asyncio.QueueEmpty:
                logger.warning(
                    "Inbox was unexpectedly empty during drop_oldest: agent_id=%s",
                    agent_id,
                )
        elif policy == OverflowPolicy.DROP_NEW:
            if self._metrics:
                self._metrics.actor_inbox_dropped_new_total += 1
            logger.warning("Dropped new event due to inbox overflow: agent_id=%s", agent_id)
        elif policy == OverflowPolicy.REJECT:
            if self._metrics:
                self._metrics.actor_inbox_rejected_total += 1
            logger.warning("Rejected event due to inbox overflow: agent_id=%s", agent_id)

        self._refresh_pending_inbox_items()

    def get_or_create_actor(self, node_id: str) -> Actor:
        """Get an existing actor or create a new one for the given node."""
        if node_id not in self._actors:
            actor = Actor(
                node_id=node_id,
                event_store=self._event_store,
                node_store=self._node_store,
                workspace_service=self._workspace_service,
                config=self._config,
                semaphore=self._semaphore,
                metrics=self._metrics,
                search_service=self._search_service,
                broker=self._broker,
            )
            actor.start()
            self._actors[node_id] = actor
            self._refresh_actor_gauges()
            logger.debug("Created actor for %s", node_id)
        return self._actors[node_id]

    async def run_forever(self) -> None:
        """Run until stopped. Actors process their own inboxes."""
        self._running = True
        try:
            while self._running:
                await asyncio.sleep(1.0)
                await self._evict_idle()
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the runner to stop."""
        self._running = False
        self._accepting_events = False

    async def stop_and_wait(self) -> None:
        """Stop all actors and wait for them to finish."""
        self._running = False
        self._accepting_events = False
        tasks = []
        for actor in self._actors.values():
            tasks.append(actor.stop())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._actors.clear()
        self._refresh_actor_gauges()

    async def _evict_idle(self, max_idle_seconds: float | None = None) -> None:
        """Stop and remove actors that have been idle longer than threshold."""
        idle_timeout = (
            self._config.runtime.actor_idle_timeout_s
            if max_idle_seconds is None
            else max_idle_seconds
        )
        now = time.time()
        to_evict = [
            node_id
            for node_id, actor in self._actors.items()
            if now - actor.last_active > idle_timeout and actor.inbox.empty()
        ]
        for node_id in to_evict:
            actor = self._actors.pop(node_id)
            await actor.stop()
            logger.debug("Evicted idle actor: %s", node_id)
        if to_evict:
            self._refresh_actor_gauges()

    @property
    def actors(self) -> dict[str, Actor]:
        """Read-only access to actor registry (for observability)."""
        return dict(self._actors)

    def _refresh_actor_gauges(self) -> None:
        if self._metrics is None:
            return
        self._metrics.active_actors = len(self._actors)
        self._refresh_pending_inbox_items()

    def _refresh_pending_inbox_items(self) -> None:
        if self._metrics is None:
            return
        self._metrics.pending_inbox_items = sum(
            actor.inbox.qsize() for actor in self._actors.values()
        )


__all__ = ["ActorPool"]
