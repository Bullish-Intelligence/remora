"""Actor orchestration."""

from __future__ import annotations

import asyncio
import time
import uuid

from structured_agents import Message

from remora.core.agents.outbox import Outbox
from remora.core.agents.prompt import PromptBuilder
from remora.core.agents.trigger import Trigger, TriggerPolicy
from remora.core.agents.turn import AgentTurnExecutor
from remora.core.events.store import EventStore
from remora.core.events.types import Event
from remora.core.model.config import Config
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.services.rate_limit import SlidingWindowRateLimiter
from remora.core.services.search import SearchServiceProtocol
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import CairnWorkspaceService


class Actor:
    """Per-agent actor with inbox, outbox, and sequential processing loop."""

    def __init__(
        self,
        node_id: str,
        event_store: EventStore,
        node_store: NodeStore,
        workspace_service: CairnWorkspaceService,
        config: Config,
        semaphore: asyncio.Semaphore,
        metrics: Metrics | None = None,
        search_service: SearchServiceProtocol | None = None,
        broker: HumanInputBroker | None = None,
    ) -> None:
        self.node_id = node_id
        self.inbox: asyncio.Queue[Event | None] = asyncio.Queue(
            maxsize=config.runtime.actor_inbox_max_items
        )
        self._event_store = event_store
        self._task: asyncio.Task | None = None
        self._last_active: float = time.time()
        self._history: list[Message] = []
        self._send_message_limiter = SlidingWindowRateLimiter(
            max_requests=config.runtime.send_message_rate_limit,
            window_seconds=config.runtime.send_message_rate_window_s,
        )

        self._trigger_policy = TriggerPolicy(config)
        self._prompt_builder = PromptBuilder(config)
        self._turn_executor = AgentTurnExecutor(
            node_store=node_store,
            event_store=event_store,
            workspace_service=workspace_service,
            config=config,
            semaphore=semaphore,
            metrics=metrics,
            history=self._history,
            prompt_builder=self._prompt_builder,
            trigger_policy=self._trigger_policy,
            search_service=search_service,
            send_message_limiter=self._send_message_limiter,
            broker=broker,
            max_model_retries=config.runtime.max_model_retries,
        )

    @property
    def last_active(self) -> float:
        return self._last_active

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def history(self) -> list[Message]:
        """Read-only access to conversation history for observability."""
        return list(self._history)

    def start(self) -> None:
        """Launch the actor's processing loop as a managed asyncio.Task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"actor-{self.node_id}")

    async def stop(self) -> None:
        """Stop the processing loop and wait for it to finish."""
        if self._task is not None and not self._task.done():
            self.inbox.put_nowait(None)
            await self._task
        self._task = None

    async def _run(self) -> None:
        """Main processing loop: consume inbox events one at a time."""
        try:
            while True:
                event = await self.inbox.get()
                if event is None:
                    break
                self._last_active = time.time()
                correlation_id = event.correlation_id or str(uuid.uuid4())
                if not self._trigger_policy.should_trigger(correlation_id):
                    continue

                outbox = Outbox(
                    actor_id=self.node_id,
                    event_store=self._event_store,
                    correlation_id=correlation_id,
                )
                trigger = Trigger(
                    node_id=self.node_id,
                    correlation_id=correlation_id,
                    event=event,
                )
                await self._execute_turn(trigger, outbox)
        except asyncio.CancelledError:
            return

    async def _execute_turn(self, trigger: Trigger, outbox: Outbox) -> None:
        await self._turn_executor.execute_turn(trigger, outbox)


__all__ = ["Actor"]
