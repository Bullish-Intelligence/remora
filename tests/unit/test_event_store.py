from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from remora.core.events import (
    AgentMessageEvent,
    AgentStartEvent,
    Event,
    EventBus,
    EventStore,
    SubscriptionPattern,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.storage.db import open_database
from remora.core.storage.transaction import TransactionContext


@pytest_asyncio.fixture
async def event_env(tmp_path):
    """Standard EventStore wiring for tests."""
    db = await open_database(tmp_path / "events.db")
    bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, bus, dispatcher)
    subs = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subs
    store = EventStore(db=db, event_bus=bus, dispatcher=dispatcher, tx=tx)
    await store.create_tables()
    yield store, bus, db
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_append_returns_id(event_env) -> None:
    store, _bus, _db = event_env
    first = await store.append(AgentStartEvent(agent_id="a"))
    second = await store.append(AgentStartEvent(agent_id="b"))
    assert first == 1
    assert second == 2


@pytest.mark.asyncio
async def test_eventstore_query_events(event_env) -> None:
    store, _bus, _db = event_env
    await store.append(AgentStartEvent(agent_id="a"))
    await store.append(AgentMessageEvent(from_agent="a", to_agent="b", content="hello"))
    events = await store.get_events(limit=2)
    assert len(events) == 2
    assert events[0]["event_type"] == "agent_message"
    assert events[1]["event_type"] == "agent_start"


@pytest.mark.asyncio
async def test_eventstore_query_events_with_filters(event_env) -> None:
    store, _bus, _db = event_env
    await store.append(
        AgentMessageEvent(
            from_agent="a",
            to_agent="b",
            content="m1",
            correlation_id="corr-1",
        )
    )
    await store.append(
        AgentMessageEvent(
            from_agent="a",
            to_agent="c",
            content="m2",
            correlation_id="corr-2",
        )
    )
    await store.append(AgentStartEvent(agent_id="worker", correlation_id="corr-1"))

    by_type = await store.get_events(limit=10, event_type="agent_start")
    assert len(by_type) == 1
    assert by_type[0]["event_type"] == "agent_start"

    by_corr = await store.get_events(limit=10, correlation_id="corr-2")
    assert len(by_corr) == 1
    assert by_corr[0]["payload"]["content"] == "m2"

    combined = await store.get_events(
        limit=10,
        event_type="agent_message",
        correlation_id="corr-1",
    )
    assert len(combined) == 1
    assert combined[0]["payload"]["content"] == "m1"


@pytest.mark.asyncio
async def test_eventstore_query_by_agent(event_env) -> None:
    store, _bus, _db = event_env
    await store.append(AgentStartEvent(agent_id="target"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="target", content="inbound"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="other", content="skip"))
    events = await store.get_events_for_agent("target", limit=10)
    event_types = [event["event_type"] for event in events]
    assert event_types.count("agent_start") == 1
    assert event_types.count("agent_message") == 1


@pytest.mark.asyncio
async def test_eventstore_get_latest_event_by_type(event_env) -> None:
    store, _bus, _db = event_env
    await store.append(AgentStartEvent(agent_id="target"))
    await store.append(AgentMessageEvent(from_agent="x", to_agent="target", content="first"))
    await store.append(AgentMessageEvent(from_agent="target", to_agent="y", content="latest"))

    event = await store.get_latest_event_by_type("target", "agent_message")
    assert event is not None
    assert event["event_type"] == "agent_message"
    assert event["payload"]["content"] == "latest"


@pytest.mark.asyncio
async def test_eventstore_get_latest_event_by_type_returns_none(event_env) -> None:
    store, _bus, _db = event_env
    await store.append(AgentStartEvent(agent_id="target"))

    event = await store.get_latest_event_by_type("target", "agent_message")
    assert event is None


@pytest.mark.asyncio
async def test_eventstore_trigger_flow(event_env) -> None:
    store, _bus, _db = event_env
    await store.subscriptions.register("agent-b", SubscriptionPattern(to_agent="b"))
    routed: list[tuple[str, Event]] = []
    store.dispatcher.router = lambda agent_id, event: routed.append((agent_id, event))

    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    await store.append(event)

    assert len(routed) == 1
    assert routed[0][0] == "agent-b"
    assert routed[0][1] == event


@pytest.mark.asyncio
async def test_eventstore_forwards_to_bus(tmp_path: Path) -> None:
    bus = EventBus()
    seen: list[str] = []

    def handler(event) -> None:
        seen.append(event.event_type)

    bus.subscribe_all(handler)
    db = await open_database(tmp_path / "events.db")
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, bus, dispatcher)
    subs = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subs
    store = EventStore(db=db, event_bus=bus, dispatcher=dispatcher, tx=tx)
    await store.create_tables()
    await store.append(AgentStartEvent(agent_id="a"))
    assert seen == ["agent_start"]
    await db.close()


@pytest.mark.asyncio
async def test_eventstore_batch_uses_single_commit(event_env, monkeypatch) -> None:
    store, _bus, db = event_env

    commit_count = 0
    original_commit = db.commit

    async def counting_commit() -> None:
        nonlocal commit_count
        commit_count += 1
        await original_commit()

    monkeypatch.setattr(db, "commit", counting_commit)
    commit_count = 0

    async with store.batch():
        for index in range(10):
            await store.append(AgentStartEvent(agent_id=f"a{index}"))

    assert commit_count == 1
