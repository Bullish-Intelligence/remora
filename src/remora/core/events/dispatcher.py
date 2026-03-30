"""Trigger dispatch: routes events to matching agents via subscriptions."""

from __future__ import annotations

import logging
from collections.abc import Callable

from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.events.types import Event

logger = logging.getLogger(__name__)


class TriggerDispatcher:
    """Routes persisted events to agent inboxes via subscription matching.

    The dispatcher resolves which agents care about an event, then
    delivers the event to each agent's inbox via a router callback.
    """

    def __init__(
        self,
        subscriptions: SubscriptionRegistry | None = None,
        router: Callable[[str, Event], None] | None = None,
    ):
        self._subscriptions = subscriptions
        self._router = router

    @property
    def router(self) -> Callable[[str, Event], None] | None:
        return self._router

    @router.setter
    def router(self, value: Callable[[str, Event], None]) -> None:
        self._router = value

    async def dispatch(self, event: Event) -> None:
        """Match event against subscriptions and route to agent inboxes."""
        if self._router is None or self._subscriptions is None:
            return
        matching_agents = await self._subscriptions.get_matching_agents(event)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Dispatch event=%s corr=%s matched_agents=%d",
                event.event_type,
                event.correlation_id,
                len(matching_agents),
            )
        for agent_id in matching_agents:
            self._router(agent_id, event)

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        if self._subscriptions is None:
            raise RuntimeError("TriggerDispatcher.subscriptions not yet wired")
        return self._subscriptions

    @subscriptions.setter
    def subscriptions(self, value: SubscriptionRegistry) -> None:
        self._subscriptions = value


__all__ = ["TriggerDispatcher"]
