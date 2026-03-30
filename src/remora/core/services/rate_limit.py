"""Shared rate limiting primitives."""

from __future__ import annotations

import time
from collections import deque


class SlidingWindowRateLimiter:
    """Per-key sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max(1, int(max_requests))
        self._window_seconds = max(0.001, float(window_seconds))
        self._timestamps: dict[str, deque[float]] = {}

    def allow(self, key: str = "__global__") -> bool:
        now = time.time()
        timestamps = self._timestamps.setdefault(key, deque())
        cutoff = now - self._window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= self._max_requests:
            return False
        timestamps.append(now)
        return True


__all__ = ["SlidingWindowRateLimiter"]
