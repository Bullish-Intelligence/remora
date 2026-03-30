from __future__ import annotations

from remora.core.services.metrics import Metrics


def test_metrics_snapshot() -> None:
    metrics = Metrics(
        agent_turns_total=3,
        agent_turns_failed=1,
        events_emitted_total=9,
        workspace_provisions_total=4,
        workspace_cache_hits=6,
        active_actors=2,
        pending_inbox_items=5,
    )
    snapshot = metrics.snapshot()
    assert set(snapshot.keys()) == {
        "agent_turns_total",
        "agent_turns_failed",
        "events_emitted_total",
        "workspace_provisions_total",
        "workspace_cache_hits",
        "workspace_cache_hit_rate",
        "active_actors",
        "pending_inbox_items",
        "actor_inbox_overflow_total",
        "actor_inbox_dropped_oldest_total",
        "actor_inbox_dropped_new_total",
        "actor_inbox_rejected_total",
        "uptime_seconds",
    }
    assert snapshot["agent_turns_total"] == 3
    assert snapshot["workspace_cache_hit_rate"] == 0.6
    assert snapshot["actor_inbox_overflow_total"] == 0
    assert snapshot["actor_inbox_dropped_oldest_total"] == 0
    assert snapshot["actor_inbox_dropped_new_total"] == 0
    assert snapshot["actor_inbox_rejected_total"] == 0


def test_cache_hit_rate_calculation() -> None:
    metrics = Metrics()
    assert metrics.cache_hit_rate == 0.0

    metrics = Metrics(workspace_cache_hits=5)
    assert metrics.cache_hit_rate == 1.0

    metrics = Metrics(workspace_provisions_total=4, workspace_cache_hits=0)
    assert metrics.cache_hit_rate == 0.0
