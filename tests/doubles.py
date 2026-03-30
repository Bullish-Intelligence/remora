"""Test doubles shared across test modules."""

from __future__ import annotations

from remora.core.events.types import Event


class RecordingOutbox:
    """Outbox test double that records emitted events without persistence."""

    def __init__(self, actor_id: str = "test") -> None:
        self._actor_id = actor_id
        self._correlation_id: str | None = None
        self._sequence = 0
        self.events: list[Event] = []

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def correlation_id(self) -> str | None:
        return self._correlation_id

    @correlation_id.setter
    def correlation_id(self, value: str | None) -> None:
        self._correlation_id = value

    @property
    def sequence(self) -> int:
        return self._sequence

    async def emit(self, event: Event) -> int:
        self._sequence += 1
        if not event.correlation_id and self._correlation_id:
            event.correlation_id = self._correlation_id
        self.events.append(event)
        return self._sequence


__all__ = ["RecordingOutbox"]
