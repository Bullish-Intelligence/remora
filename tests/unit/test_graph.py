from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from tests.factories import make_node

from remora.core.events import (
    AgentStartEvent,
    EventBus,
    EventStore,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.model.types import NodeStatus, NodeType
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext


@pytest_asyncio.fixture
async def tx(db):
    """Minimal TransactionContext for testing."""
    bus = EventBus()
    dispatcher = TriggerDispatcher()
    context = TransactionContext(db, bus, dispatcher)
    subs = SubscriptionRegistry(db, tx=context)
    dispatcher.subscriptions = subs
    return context


@pytest.mark.asyncio
async def test_nodestore_upsert_and_get(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    node = make_node("src/app.py::a")
    await store.upsert_node(node)
    got = await store.get_node(node.node_id)
    assert got is not None
    assert got.model_dump() == node.model_dump()


@pytest.mark.asyncio
async def test_nodestore_list_with_filters(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", node_type="function", status="idle"))
    await store.upsert_node(make_node("src/app.py::B", node_type="class", status="running"))
    await store.upsert_node(
        make_node(
            "src/other.py::c",
            node_type="function",
            status="idle",
            file_path="src/other.py",
        )
    )

    by_type = await store.list_nodes(node_type=NodeType.CLASS)
    by_status = await store.list_nodes(status=NodeStatus.RUNNING)
    by_path = await store.list_nodes(file_path="src/other.py")

    assert [n.node_id for n in by_type] == ["src/app.py::B"]
    assert [n.node_id for n in by_status] == ["src/app.py::B"]
    assert [n.node_id for n in by_path] == ["src/other.py::c"]


@pytest.mark.asyncio
async def test_nodestore_get_nodes_by_ids(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))

    nodes = await store.get_nodes_by_ids(["src/app.py::b", "src/app.py::a", "missing"])
    assert {node.node_id for node in nodes} == {"src/app.py::a", "src/app.py::b"}


@pytest.mark.asyncio
async def test_nodestore_count_nodes(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    assert await store.count_nodes() == 2


@pytest.mark.asyncio
async def test_nodestore_delete(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    assert await store.delete_node("src/app.py::a")
    assert await store.get_node("src/app.py::a") is None
    assert await store.get_edges("src/app.py::a") == []


@pytest.mark.asyncio
async def test_nodestore_transition_status_updates_node(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    node = make_node("src/app.py::a", status="idle")
    await store.upsert_node(node)

    assert await store.transition_status(node.node_id, NodeStatus.RUNNING)
    got = await store.get_node(node.node_id)
    assert got is not None
    assert got.status == NodeStatus.RUNNING
    assert got.source_hash == node.source_hash


@pytest.mark.asyncio
async def test_nodestore_add_edge(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))

    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    edges = await store.get_edges("src/app.py::a", direction="outgoing")
    assert len(edges) == 1
    assert edges[0].from_id == "src/app.py::a"
    assert edges[0].to_id == "src/app.py::b"
    assert edges[0].edge_type == "calls"


@pytest.mark.asyncio
async def test_nodestore_edge_directions(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    await store.add_edge("src/app.py::c", "src/app.py::a", "calls")

    outgoing = await store.get_edges("src/app.py::a", direction="outgoing")
    incoming = await store.get_edges("src/app.py::a", direction="incoming")
    both = await store.get_edges("src/app.py::a", direction="both")

    assert len(outgoing) == 1
    assert outgoing[0].to_id == "src/app.py::b"
    assert len(incoming) == 1
    assert incoming[0].from_id == "src/app.py::c"
    assert len(both) == 2


@pytest.mark.asyncio
async def test_nodestore_edge_uniqueness(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))

    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    await store.add_edge("src/app.py::a", "src/app.py::b", "calls")
    edges = await store.get_edges("src/app.py::a", direction="outgoing")
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_shared_db_coexistence(db, tx) -> None:
    node_store = NodeStore(db, tx=tx)
    dispatcher = TriggerDispatcher()
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    event_store = EventStore(
        db=db,
        event_bus=EventBus(),
        dispatcher=dispatcher,
        tx=tx,
    )
    await node_store.create_tables()
    await event_store.create_tables()
    await node_store.upsert_node(make_node("src/app.py::a"))
    event_id = await event_store.append(AgentStartEvent(agent_id="src/app.py::a"))
    got = await node_store.get_node("src/app.py::a")

    assert got is not None
    assert event_id == 1


@pytest.mark.asyncio
async def test_nodestore_transition_status_valid(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="idle"))

    assert await store.transition_status("src/app.py::a", NodeStatus.RUNNING)
    updated = await store.get_node("src/app.py::a")
    assert updated is not None
    assert updated.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_nodestore_transition_status_invalid(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="idle"))

    assert not await store.transition_status("src/app.py::a", NodeStatus.ERROR)
    updated = await store.get_node("src/app.py::a")
    assert updated is not None
    assert updated.status == NodeStatus.IDLE


@pytest.mark.asyncio
async def test_nodestore_transition_status_awaiting_input(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="running"))

    assert await store.transition_status("src/app.py::a", NodeStatus.AWAITING_INPUT)
    paused = await store.get_node("src/app.py::a")
    assert paused is not None
    assert paused.status == NodeStatus.AWAITING_INPUT

    assert await store.transition_status("src/app.py::a", NodeStatus.RUNNING)
    resumed = await store.get_node("src/app.py::a")
    assert resumed is not None
    assert resumed.status == NodeStatus.RUNNING


@pytest.mark.asyncio
async def test_nodestore_transition_status_awaiting_review(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="running"))

    assert await store.transition_status("src/app.py::a", NodeStatus.AWAITING_REVIEW)
    review = await store.get_node("src/app.py::a")
    assert review is not None
    assert review.status == NodeStatus.AWAITING_REVIEW

    assert await store.transition_status("src/app.py::a", NodeStatus.IDLE)
    idle = await store.get_node("src/app.py::a")
    assert idle is not None
    assert idle.status == NodeStatus.IDLE


@pytest.mark.asyncio
async def test_nodestore_transition_status_sequential_updates_both_succeed(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a", status="running"))

    results = await asyncio.gather(
        store.transition_status("src/app.py::a", NodeStatus.AWAITING_INPUT),
        store.transition_status("src/app.py::a", NodeStatus.ERROR),
    )

    # Both succeed because aiosqlite serializes on a single connection
    assert all(results), "both transitions succeed sequentially"
    updated = await store.get_node("src/app.py::a")
    assert updated is not None
    # The second gather operand runs last, so its status wins
    assert updated.status == NodeStatus.ERROR


@pytest.mark.asyncio
async def test_nodestore_get_children(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(
        make_node(
            "src",
            node_type="directory",
            file_path="src",
            parent_id=".",
            start_line=0,
            end_line=0,
            text="",
            source_hash="hash-src",
        )
    )
    await store.upsert_node(make_node("src/app.py::a", parent_id="src"))
    await store.upsert_node(make_node("src/lib", node_type="directory", parent_id="src"))

    children = await store.get_children("src")
    assert [node.node_id for node in children] == ["src/app.py::a", "src/lib"]


@pytest.mark.asyncio
async def test_nodestore_batch_commits_once_for_grouped_writes(db, tx, monkeypatch) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()

    commit_calls = 0
    real_commit = db.commit

    async def counted_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        await real_commit()

    monkeypatch.setattr(db, "commit", counted_commit)

    async with store.batch():
        await store.upsert_node(make_node("src/app.py::a"))
        await store.upsert_node(make_node("src/app.py::b"))
        await store.add_edge("src/app.py::a", "src/app.py::b", "calls")

    assert commit_calls == 1


@pytest.mark.asyncio
async def test_batch_rolls_back_on_exception(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    sample_node = make_node("src/app.py::rollback")

    with pytest.raises(ValueError, match="deliberate failure"):
        async with store.batch():
            await store.upsert_node(sample_node)
            raise ValueError("deliberate failure")

    result = await store.get_node(sample_node.node_id)
    assert result is None


@pytest.mark.asyncio
async def test_nodestore_get_edges_by_type(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::c", "contains")

    imports_out = await store.get_edges_by_type("src/app.py::a", "imports", direction="outgoing")
    assert len(imports_out) == 1
    assert imports_out[0].to_id == "src/app.py::b"
    assert imports_out[0].edge_type == "imports"

    contains_out = await store.get_edges_by_type(
        "src/app.py::a",
        "contains",
        direction="outgoing",
    )
    assert len(contains_out) == 1
    assert contains_out[0].to_id == "src/app.py::c"

    imports_in = await store.get_edges_by_type("src/app.py::b", "imports", direction="incoming")
    assert len(imports_in) == 1
    assert imports_in[0].from_id == "src/app.py::a"

    both = await store.get_edges_by_type("src/app.py::a", "imports", direction="both")
    assert len(both) == 1


@pytest.mark.asyncio
async def test_nodestore_get_edges_by_type_invalid_direction(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    with pytest.raises(ValueError, match="direction"):
        await store.get_edges_by_type("src/app.py::a", "imports", direction="invalid")


@pytest.mark.asyncio
async def test_nodestore_get_importers(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::b", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::b", "contains")

    importers = await store.get_importers("src/app.py::c")
    assert sorted(importers) == ["src/app.py::a", "src/app.py::b"]

    importers_b = await store.get_importers("src/app.py::b")
    assert importers_b == []


@pytest.mark.asyncio
async def test_nodestore_get_dependencies(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::b", "contains")

    deps = await store.get_dependencies("src/app.py::a")
    assert sorted(deps) == ["src/app.py::b", "src/app.py::c"]


@pytest.mark.asyncio
async def test_nodestore_delete_edges_by_type(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::c", "imports")
    await store.add_edge("src/app.py::a", "src/app.py::b", "contains")

    deleted = await store.delete_edges_by_type("src/app.py::a", "imports")
    assert deleted == 2

    remaining = await store.get_edges("src/app.py::a", direction="outgoing")
    assert len(remaining) == 1
    assert remaining[0].edge_type == "contains"

    assert await store.get_importers("src/app.py::b") == []


@pytest.mark.asyncio
async def test_nodestore_delete_outgoing_edges_by_type_preserves_incoming(db, tx) -> None:
    store = NodeStore(db, tx=tx)
    await store.create_tables()
    await store.upsert_node(make_node("src/app.py::a"))
    await store.upsert_node(make_node("src/app.py::b"))
    await store.upsert_node(make_node("src/app.py::c"))
    await store.add_edge("src/app.py::a", "src/app.py::b", "imports")
    await store.add_edge("src/app.py::c", "src/app.py::b", "imports")

    deleted = await store.delete_outgoing_edges_by_type("src/app.py::b", "imports")
    assert deleted == 0

    deleted = await store.delete_outgoing_edges_by_type("src/app.py::a", "imports")
    assert deleted == 1

    remaining_importers = await store.get_importers("src/app.py::b")
    assert remaining_importers == ["src/app.py::c"]
