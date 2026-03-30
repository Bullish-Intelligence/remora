"""Trigger primitives and policy for actor execution."""

from __future__ import annotations

import time
from dataclasses import dataclass

from remora.core.events.types import Event
from remora.core.model.config import Config

_DEPTH_TTL_MS = 5 * 60 * 1000
_DEPTH_CLEANUP_INTERVAL = 100


@dataclass
class Trigger:
    """A trigger waiting to be executed."""

    node_id: str
    correlation_id: str
    event: Event | None = None


class TriggerPolicy:
    """Cooldown/depth trigger policy with bounded state cleanup."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._max_reactive_turns_per_correlation = max(
            1,
            int(config.runtime.max_reactive_turns_per_correlation),
        )
        self.last_trigger_ms: float = 0.0
        self.depths: dict[str, int] = {}
        self.depth_timestamps: dict[str, float] = {}
        self.correlation_turn_counts: dict[str, int] = {}
        self.correlation_turn_timestamps: dict[str, float] = {}
        self.trigger_checks = 0

    def should_trigger(self, correlation_id: str) -> bool:
        """Return True when cooldown and depth constraints allow triggering."""
        now_ms = time.time() * 1000.0
        self.trigger_checks += 1
        if self.trigger_checks >= _DEPTH_CLEANUP_INTERVAL:
            self.cleanup_depth_state(now_ms)
            self.trigger_checks = 0

        if now_ms - self.last_trigger_ms < self._config.runtime.trigger_cooldown_ms:
            return False
        self.last_trigger_ms = now_ms

        depth = self.depths.get(correlation_id, 0)
        if depth >= self._config.runtime.max_trigger_depth:
            return False

        reactive_turns = self.correlation_turn_counts.get(correlation_id, 0)
        if reactive_turns >= self._max_reactive_turns_per_correlation:
            return False

        self.depths[correlation_id] = depth + 1
        self.depth_timestamps[correlation_id] = now_ms
        self.correlation_turn_counts[correlation_id] = reactive_turns + 1
        self.correlation_turn_timestamps[correlation_id] = now_ms
        return True

    def cleanup_depth_state(self, now_ms: float) -> None:
        cutoff = now_ms - _DEPTH_TTL_MS
        stale_depth_ids = [
            correlation_id
            for correlation_id, timestamp_ms in self.depth_timestamps.items()
            if timestamp_ms < cutoff
        ]
        for correlation_id in stale_depth_ids:
            self.depth_timestamps.pop(correlation_id, None)
            self.depths.pop(correlation_id, None)

        stale_turn_ids = [
            correlation_id
            for correlation_id, timestamp_ms in self.correlation_turn_timestamps.items()
            if timestamp_ms < cutoff
        ]
        for correlation_id in stale_turn_ids:
            self.correlation_turn_timestamps.pop(correlation_id, None)
            self.correlation_turn_counts.pop(correlation_id, None)

    def release_depth(self, correlation_id: str | None) -> None:
        if correlation_id is None:
            return
        remaining = self.depths.get(correlation_id, 1) - 1
        if remaining <= 0:
            self.depths.pop(correlation_id, None)
            self.depth_timestamps.pop(correlation_id, None)
        else:
            self.depths[correlation_id] = remaining
            self.depth_timestamps[correlation_id] = time.time() * 1000.0


__all__ = ["Trigger", "TriggerPolicy"]
