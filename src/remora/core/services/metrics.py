"""Simple in-memory metrics collector."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Metrics:
    """Counters and gauges for system observability."""

    # Counters (monotonically increasing)
    agent_turns_total: int = 0
    agent_turns_failed: int = 0
    events_emitted_total: int = 0
    workspace_provisions_total: int = 0
    workspace_cache_hits: int = 0
    actor_inbox_overflow_total: int = 0
    actor_inbox_dropped_oldest_total: int = 0
    actor_inbox_dropped_new_total: int = 0
    actor_inbox_rejected_total: int = 0

    # Gauges (current values)
    active_actors: int = 0
    pending_inbox_items: int = 0

    # Timing
    start_time: float = field(default_factory=time.time)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def cache_hit_rate(self) -> float:
        total = self.workspace_provisions_total + self.workspace_cache_hits
        return self.workspace_cache_hits / total if total > 0 else 0.0

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of all metrics."""
        return {
            "agent_turns_total": self.agent_turns_total,
            "agent_turns_failed": self.agent_turns_failed,
            "events_emitted_total": self.events_emitted_total,
            "workspace_provisions_total": self.workspace_provisions_total,
            "workspace_cache_hits": self.workspace_cache_hits,
            "workspace_cache_hit_rate": round(self.cache_hit_rate, 3),
            "active_actors": self.active_actors,
            "pending_inbox_items": self.pending_inbox_items,
            "actor_inbox_overflow_total": self.actor_inbox_overflow_total,
            "actor_inbox_dropped_oldest_total": self.actor_inbox_dropped_oldest_total,
            "actor_inbox_dropped_new_total": self.actor_inbox_dropped_new_total,
            "actor_inbox_rejected_total": self.actor_inbox_rejected_total,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }
