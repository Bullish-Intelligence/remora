from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from remora.core.events import (
    AgentCompleteEvent,
    AgentMessageEvent,
    ContentChangedEvent,
    Event,
    NodeDiscoveredEvent,
    SubscriptionPattern,
    SubscriptionRegistry,
)


class _PathEvent(Event):
    path: str | None = None


def test_subscription_pattern_matches_exact() -> None:
    pattern = SubscriptionPattern(to_agent="b")
    assert pattern.matches(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    assert not pattern.matches(
        AgentMessageEvent(from_agent="a", to_agent="c", content="hello")
    )


def test_subscription_pattern_matches_event_type() -> None:
    pattern = SubscriptionPattern(event_types=["agent_message"])
    assert pattern.matches(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert not pattern.matches(ContentChangedEvent(path="src/app.py"))


def test_subscription_pattern_matches_path_glob() -> None:
    pattern = SubscriptionPattern(path_glob="src/**/*.py")
    assert pattern.matches(ContentChangedEvent(path="src/auth/service.py"))
    assert not pattern.matches(ContentChangedEvent(path="docs/readme.md"))


def test_subscription_pattern_matches_relative_glob_against_absolute_path() -> None:
    pattern = SubscriptionPattern(path_glob="src/**/*.py")
    assert pattern.matches(ContentChangedEvent(path="/home/user/project/src/auth/service.py"))
    assert not pattern.matches(ContentChangedEvent(path="/home/user/project/docs/readme.md"))


def test_subscription_pattern_matches_node_file_path_with_relative_glob() -> None:
    pattern = SubscriptionPattern(event_types=["node_discovered"], path_glob="src/**")
    event = NodeDiscoveredEvent(
        node_id="src/api/orders.py::create_order",
        node_type="function",
        file_path="/home/user/project/src/api/orders.py",
        name="create_order",
    )
    assert pattern.matches(event)


def test_subscription_pattern_none_matches_all() -> None:
    pattern = SubscriptionPattern()
    assert pattern.matches(AgentMessageEvent(from_agent="user", to_agent="a", content="hi"))
    assert pattern.matches(ContentChangedEvent(path="any/path.txt"))


def test_not_from_agents_excludes_matching_agent_id() -> None:
    pattern = SubscriptionPattern(
        event_types=["agent_complete"],
        not_from_agents=["observer-1"],
    )
    own_event = AgentCompleteEvent(agent_id="observer-1", result_summary="done")
    other_event = AgentCompleteEvent(agent_id="agent-a", result_summary="done")
    assert not pattern.matches(own_event)
    assert pattern.matches(other_event)


def test_not_from_agents_excludes_matching_from_agent() -> None:
    pattern = SubscriptionPattern(
        event_types=["agent_message"],
        not_from_agents=["observer-1"],
    )
    event = AgentMessageEvent(from_agent="observer-1", to_agent="agent-a", content="hi")
    assert not pattern.matches(event)


def test_not_from_agents_none_matches_all() -> None:
    pattern = SubscriptionPattern(
        event_types=["agent_complete"],
        not_from_agents=None,
    )
    event = AgentCompleteEvent(agent_id="any-agent", result_summary="done")
    assert pattern.matches(event)


@pytest.mark.asyncio
async def test_registry_register_and_match(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    matches = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert matches == ["agent-b"]


@pytest.mark.asyncio
async def test_registry_unregister(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    sub_id = await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    assert await registry.unregister(sub_id)
    matches = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert matches == []


@pytest.mark.asyncio
async def test_registry_cache_invalidation(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    first = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert first == ["agent-b"]

    await registry.register("agent-c", SubscriptionPattern(to_agent="b"))
    second = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert second == ["agent-b", "agent-c"]


@pytest.mark.asyncio
async def test_registry_not_from_agents_filter(db) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register(
        "observer-1",
        SubscriptionPattern(
            event_types=["agent_complete"],
            not_from_agents=["observer-1"],
        ),
    )

    own_event = AgentCompleteEvent(agent_id="observer-1")
    own_matches = await registry.get_matching_agents(own_event)
    assert own_matches == []

    other_event = AgentCompleteEvent(agent_id="agent-a")
    other_matches = await registry.get_matching_agents(other_event)
    assert other_matches == ["observer-1"]


@pytest.mark.asyncio
async def test_registry_register_updates_cache_incrementally(db, monkeypatch) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    first = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert first == ["agent-b"]

    async def fail_rebuild() -> None:
        raise AssertionError("cache rebuild should not be required")

    monkeypatch.setattr(registry, "_rebuild_cache", fail_rebuild)
    await registry.register("agent-c", SubscriptionPattern(to_agent="b"))
    second = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert second == ["agent-b", "agent-c"]


@pytest.mark.asyncio
async def test_registry_unregister_updates_cache_incrementally(db, monkeypatch) -> None:
    registry = SubscriptionRegistry(db)
    await registry.create_tables()
    await registry.register("agent-b", SubscriptionPattern(to_agent="b"))
    sub_c = await registry.register("agent-c", SubscriptionPattern(to_agent="b"))

    baseline = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert baseline == ["agent-b", "agent-c"]

    async def fail_rebuild() -> None:
        raise AssertionError("cache rebuild should not be required")

    monkeypatch.setattr(registry, "_rebuild_cache", fail_rebuild)

    assert await registry.unregister(sub_c)
    after_unsub = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert after_unsub == ["agent-b"]

    assert await registry.unregister_by_agent("agent-b") == 1
    after_agent_remove = await registry.get_matching_agents(
        AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    )
    assert after_agent_remove == []


@settings(max_examples=100)
@given(st.text(min_size=1, max_size=40))
def test_property_subscription_pattern_matches_same_event_type(event_type: str) -> None:
    pattern = SubscriptionPattern(event_types=[event_type])
    event = Event(event_type=event_type)
    assert pattern.matches(event)


@settings(max_examples=100)
@given(st.text(min_size=1, max_size=40), st.text(min_size=1, max_size=40))
def test_property_subscription_pattern_rejects_different_event_types(
    expected_type: str,
    actual_type: str,
) -> None:
    assume(expected_type != actual_type)
    pattern = SubscriptionPattern(event_types=[expected_type])
    event = Event(event_type=actual_type)
    assert not pattern.matches(event)


@settings(max_examples=100)
@given(
    st.lists(st.from_regex(r"[a-z]{1,8}", fullmatch=True), min_size=1, max_size=4),
)
def test_property_subscription_path_glob_matches_suffix(path_parts: list[str]) -> None:
    suffix = path_parts[-1]
    path = f"src/{'/'.join(path_parts)}.py"
    pattern = SubscriptionPattern(path_glob=f"**/{suffix}.py")
    event = _PathEvent(event_type="content_changed", path=path)
    assert pattern.matches(event)
