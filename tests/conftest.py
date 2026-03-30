"""Shared pytest fixtures."""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio

from remora.core.storage.db import open_database


def _remove_closed_root_stream_handlers() -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        stream = getattr(handler, "stream", None)
        if stream is None or not getattr(stream, "closed", False):
            continue
        root_logger.removeHandler(handler)
        handler.close()


@pytest.fixture(autouse=True)
def cleanup_closed_root_stream_handlers():
    _remove_closed_root_stream_handlers()
    yield
    _remove_closed_root_stream_handlers()


@pytest_asyncio.fixture
async def db(tmp_path):
    """Shared SQLite fixture configured with WAL mode."""
    database = await open_database(tmp_path / "test.db")
    yield database
    await database.close()


@pytest_asyncio.fixture
async def db_with_deps(tmp_path):
    """Database with NodeStore and EventStore dependencies initialized."""
    from remora.core.events import EventBus, EventStore, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.graph import NodeStore
    from remora.core.storage.transaction import TransactionContext

    database = await open_database(tmp_path / "test.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(database, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(database, tx=tx)
    dispatcher.subscriptions = subscriptions
    node_store = NodeStore(database, tx=tx)
    await node_store.create_tables()
    event_store = EventStore(database, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()

    yield database, node_store, event_store, tx

    await database.close()
