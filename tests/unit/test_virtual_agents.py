from __future__ import annotations

from remora.code.virtual_agents import VirtualAgentManager
from remora.core.model.config import VirtualAgentConfig, VirtualSubscriptionConfig


def test_virtual_agent_manager_builds_patterns() -> None:
    spec = VirtualAgentConfig(
        id="companion",
        role="test-agent",
        subscriptions=(
            VirtualSubscriptionConfig(event_types=("node_changed",), path_glob="src/**"),
        ),
    )

    patterns = VirtualAgentManager.build_patterns(spec)
    assert len(patterns) == 1
    assert patterns[0].event_types == ["node_changed"]
    assert patterns[0].path_glob == "src/**"


def test_virtual_agent_hash_changes_when_spec_changes() -> None:
    first = VirtualAgentConfig(
        id="companion",
        role="test-agent",
        subscriptions=(VirtualSubscriptionConfig(event_types=("node_changed",)),),
    )
    second = VirtualAgentConfig(
        id="companion",
        role="other-agent",
        subscriptions=(VirtualSubscriptionConfig(event_types=("node_changed",)),),
    )

    first_hash = VirtualAgentManager.build_hash(first)
    second_hash = VirtualAgentManager.build_hash(second)

    assert first_hash != second_hash
