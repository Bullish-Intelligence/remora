"""Unified transaction context for NodeStore and EventStore."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import aiosqlite

from remora.core.events.bus import EventBus
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.events.types import Event


class TransactionContext:
    """Shared transaction depth tracker for a single DB connection."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        event_bus: EventBus,
        dispatcher: TriggerDispatcher,
    ):
        self._db = db
        self._event_bus = event_bus
        self._dispatcher = dispatcher
        self._depth = 0
        self._deferred_events: list[Event] = []

    @asynccontextmanager
    async def batch(self):
        """Nest-safe batch context. Only the outermost batch commits and fans out."""
        self._depth += 1
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            if self._depth == 1:
                await self._db.rollback()
            raise
        finally:
            self._depth -= 1
            if self._depth == 0:
                if not failed:
                    await self._db.commit()
                    events = list(self._deferred_events)
                    self._deferred_events.clear()
                    async with asyncio.TaskGroup() as tg:
                        for event in events:
                            tg.create_task(self._fan_out(event))
                else:
                    self._deferred_events.clear()

    @property
    def in_batch(self) -> bool:
        return self._depth > 0

    async def _fan_out(self, event: Event) -> None:
        """Emit to bus and dispatch to subscriptions for a single event."""
        await self._event_bus.emit(event)
        await self._dispatcher.dispatch(event)

    def defer_event(self, event: Event) -> None:
        """Buffer an event for fan-out after the outermost batch commits."""
        self._deferred_events.append(event)


__all__ = ["TransactionContext"]
