from __future__ import annotations

import pytest

from remora.core.events import AgentMessageEvent, EventBus, EventStore, SubscriptionRegistry
from remora.core.events.dispatcher import TriggerDispatcher
from remora.core.storage.db import open_database
from remora.core.storage.transaction import TransactionContext


@pytest.mark.asyncio
async def test_event_store_sets_event_id_and_replay_uses_integer_ids(tmp_path) -> None:
    db = await open_database(tmp_path / "events.db")
    bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, bus, dispatcher)
    subs = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subs
    store = EventStore(db=db, event_bus=bus, dispatcher=dispatcher, tx=tx)
    await store.create_tables()

    event = AgentMessageEvent(from_agent="user", to_agent="src/app.py::a", content="resume-test")
    event_id = await store.append(event)

    assert event.event_id == event_id

    rows = await store.get_events_after(str(event_id - 1))
    assert rows
    assert rows[0]["id"] == event_id
    assert rows[0]["payload"]["content"] == "resume-test"

    await db.close()
