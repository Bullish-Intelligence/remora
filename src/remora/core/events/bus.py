"""In-memory event bus."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from remora.core.events.types import Event, EventHandler
from remora.core.model.errors import RemoraError

logger = logging.getLogger(__name__)


class EventBus:
    """In-memory event dispatch with string-keyed subscriptions."""

    def __init__(self, max_concurrent_handlers: int = 100) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)

    async def emit(self, event: Event) -> None:
        """Emit an event to matching string-keyed and global handlers."""
        event_type_key = event.event_type
        await self._dispatch_handlers(
            self._handlers.get(event_type_key, []),
            event,
            self._semaphore,
        )
        await self._dispatch_handlers(self._all_handlers, event, self._semaphore)

    @staticmethod
    async def _dispatch_handlers(
        handlers: list[EventHandler],
        event: Event,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        async_handlers: list[EventHandler] = []
        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                async_handlers.append(handler)
                continue
            try:
                handler(event)
            except (RemoraError, OSError) as exc:
                logger.exception(
                    "Event handler failed for %s: %s",
                    event.event_type,
                    exc,
                    exc_info=exc,
                )
        if async_handlers:
            async with asyncio.TaskGroup() as tg:
                for handler in async_handlers:
                    if semaphore is None:
                        tg.create_task(EventBus._run_guarded(handler, event))
                    else:
                        tg.create_task(
                            EventBus._run_guarded(handler, event, semaphore=semaphore)
                        )

    @staticmethod
    async def _run_guarded(
        handler: Any,
        event: Event,
        *,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        """Run an async handler, catching errors so TaskGroup doesn't abort siblings."""
        try:
            if semaphore is not None:
                async with semaphore:
                    await handler(event)
            else:
                await handler(event)
        except Exception as exc:
            logger.exception(
                "Event handler failed for %s: %s",
                event.event_type,
                exc,
                exc_info=exc,
            )

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type string."""
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler for all event types."""
        self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions."""
        empty_event_types: list[str] = []
        for event_type, handlers in self._handlers.items():
            remaining = [registered for registered in handlers if registered is not handler]
            if remaining:
                self._handlers[event_type] = remaining
            else:
                empty_event_types.append(event_type)
        for event_type in empty_event_types:
            del self._handlers[event_type]
        self._all_handlers = [
            registered for registered in self._all_handlers if registered is not handler
        ]

    @asynccontextmanager
    async def stream(
        self,
        *event_types: str,
        max_buffer: int = 1000,
    ) -> AsyncIterator[AsyncIterator[Event]]:
        """Yield an async iterator of events for optional filtered types."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_buffer)
        filter_set = set(event_types) if event_types else None

        def enqueue(event: Event) -> None:
            if filter_set is None or event.event_type in filter_set:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "SSE stream buffer full, dropping event %s",
                        event.event_type,
                    )

        self.subscribe_all(enqueue)

        async def iterate() -> AsyncIterator[Event]:
            while True:
                yield await queue.get()

        try:
            yield iterate()
        finally:
            self.unsubscribe(enqueue)


__all__ = ["EventBus"]
