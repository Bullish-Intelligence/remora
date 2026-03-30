"""Human-input request/response broker."""

from __future__ import annotations

import asyncio


class HumanInputBroker:
    """Manages pending human-input response futures.

    Extracted from EventStore to respect single-responsibility:
    EventStore handles persistence and fan-out, while this broker
    handles the in-memory future lifecycle for human-input requests.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[str]] = {}

    def create_future(self, request_id: str) -> asyncio.Future[str]:
        """Create and register a pending human-input response future."""
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        return future

    def resolve(self, request_id: str, response: str) -> bool:
        """Resolve and remove a pending human-input response future."""
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(response)
        return True

    def discard(self, request_id: str) -> bool:
        """Remove an unresolved pending future (e.g. timeout/cancel)."""
        future = self._pending.pop(request_id, None)
        if future is None:
            return False
        if not future.done():
            future.cancel()
        return True


__all__ = ["HumanInputBroker"]
