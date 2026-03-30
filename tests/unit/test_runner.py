from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
import time

import pytest
import pytest_asyncio
from tests.factories import make_node

from remora.core.agents.actor import Actor, PromptBuilder, TriggerPolicy
from remora.core.model.config import (
    BehaviorConfig,
    Config,
    InfraConfig,
    OverflowPolicy,
    RuntimeConfig,
)
from remora.core.storage.db import open_database
from remora.core.events import (
    AgentMessageEvent,
    EventStore,
    SubscriptionPattern,
)
from remora.core.storage.graph import NodeStore
from remora.core.agents.runner import ActorPool
from remora.core.storage.workspace import CairnWorkspaceService

_USER_TEMPLATE = (
    "# Node: {node_full_name}\n"
    "Type: {node_type} | File: {file_path}\n"
    "Role: {role}\n\n"
    "## Source Code\n"
    "```\n"
    "{source}\n"
    "```\n\n"
    "## Trigger\n"
    "Event: {event_type}\n"
    "{event_content}\n"
)


@pytest_asyncio.fixture
async def runner_env(tmp_path: Path):
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

    db = await open_database(tmp_path / "runner.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    node_store = NodeStore(db, tx=tx)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()
    config = Config(
        infra=InfraConfig(workspace_root=".remora-runner-test"),
        runtime=RuntimeConfig(trigger_cooldown_ms=1000, max_trigger_depth=2),
        behavior=BehaviorConfig(prompt_templates={"user": _USER_TEMPLATE}),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config)

    yield runner, node_store, event_store, workspace_service

    await runner.stop_and_wait()
    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_runner_creates_actor_on_route(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    assert len(runner.actors) == 0
    actor = runner.get_or_create_actor("agent-a")
    assert isinstance(actor, Actor)
    assert actor.is_running
    assert "agent-a" in runner.actors


@pytest.mark.asyncio
async def test_runner_reuses_existing_actor(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    actor1 = runner.get_or_create_actor("agent-a")
    actor2 = runner.get_or_create_actor("agent-a")
    assert actor1 is actor2


@pytest.mark.asyncio
async def test_runner_routes_dispatch_to_actor_inbox(runner_env) -> None:
    runner, _ns, event_store, _ws = runner_env
    actor = runner.get_or_create_actor("agent-x")
    await actor.stop()
    await event_store.subscriptions.register("agent-x", SubscriptionPattern(to_agent="x"))

    event = AgentMessageEvent(from_agent="a", to_agent="x", content="hello")
    await event_store.append(event)

    assert "agent-x" in runner.actors
    assert actor.inbox.qsize() >= 1


@pytest.mark.asyncio
async def test_runner_evicts_idle_actors(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    actor = runner.get_or_create_actor("idle-agent")
    actor._last_active = 0.0
    await runner._evict_idle()
    assert "idle-agent" not in runner.actors
    assert not actor.is_running


@pytest.mark.asyncio
async def test_runner_does_not_evict_busy_actors(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    actor = runner.get_or_create_actor("busy-agent")
    actor._last_active = 0.0
    await actor.inbox.put(AgentMessageEvent(from_agent="a", to_agent="b", content="x"))
    await runner._evict_idle(max_idle_seconds=1.0)
    assert "busy-agent" in runner.actors


@pytest.mark.asyncio
async def test_runner_stop_and_wait(runner_env) -> None:
    runner, _ns, _es, _ws = runner_env
    runner.get_or_create_actor("a")
    runner.get_or_create_actor("b")
    assert len(runner.actors) == 2
    await runner.stop_and_wait()
    await runner.stop_and_wait()
    runner.stop()
    runner.stop()
    assert len(runner.actors) == 0


@pytest.mark.asyncio
async def test_runner_build_prompt_via_actor(runner_env) -> None:
    _runner, node_store, _event_store, workspace_service = runner_env
    node = make_node("src/app.py::a")
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    prompt_builder = PromptBuilder(
        Config(
            behavior=BehaviorConfig(
                prompt_templates={"user": _USER_TEMPLATE}, model_default="mock", max_turns=1
            )
        )
    )
    prompt = prompt_builder.build_user_prompt(
        node,
        AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
    )
    assert node.full_name in prompt
    assert "hello" in prompt
    assert "Type: function | File: src/app.py" in prompt


@pytest.mark.asyncio
async def test_runner_build_prompt_for_virtual_node(runner_env) -> None:
    _runner, node_store, _event_store, workspace_service = runner_env
    node = make_node(
        "test-agent",
        node_type="virtual",
        file_path="",
        text="",
        role="test-agent",
        name="test-agent",
        full_name="test-agent",
        start_line=0,
        end_line=0,
    )
    await node_store.upsert_node(node)
    ws = await workspace_service.get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    prompt_builder = PromptBuilder(
        Config(
            behavior=BehaviorConfig(
                prompt_templates={"user": _USER_TEMPLATE}, model_default="mock", max_turns=1
            )
        )
    )
    prompt = prompt_builder.build_user_prompt(
        node,
        AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
    )
    assert "Type: virtual | File: " in prompt
    assert "Role: test-agent" in prompt


@pytest.mark.asyncio
async def test_runner_handles_concurrent_triggers_across_agents(runner_env, monkeypatch) -> None:
    runner, node_store, event_store, _workspace_service = runner_env
    agent_ids = [f"src/app.py::agent_{idx}" for idx in range(5)]
    for agent_id in agent_ids:
        await node_store.upsert_node(make_node(agent_id))
        await event_store.subscriptions.register(
            agent_id,
            SubscriptionPattern(to_agent=agent_id),
        )

    processed: list[str] = []
    done = asyncio.Event()
    lock = asyncio.Lock()
    in_flight = 0
    max_in_flight = 0

    monkeypatch.setattr(TriggerPolicy, "should_trigger", lambda _self, _corr: True)

    async def fake_execute_turn(self, trigger, outbox):  # noqa: ANN001, ANN202
        del trigger, outbox
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        processed.append(self.node_id)
        async with lock:
            in_flight -= 1
        if len(processed) == 20:
            done.set()

    monkeypatch.setattr(Actor, "_execute_turn", fake_execute_turn)

    for idx in range(20):
        target_id = agent_ids[idx % len(agent_ids)]
        await event_store.append(
            AgentMessageEvent(
                from_agent="load-test",
                to_agent=target_id,
                content=f"msg-{idx}",
                correlation_id=f"corr-{idx}",
            )
        )

    await asyncio.wait_for(done.wait(), timeout=5.0)
    counts = Counter(processed)
    assert len(processed) == 20
    assert set(counts.values()) == {4}
    assert max_in_flight >= 2


@pytest.mark.asyncio
async def test_runner_passes_search_service_to_actor(runner_env, monkeypatch) -> None:
    runner, _node_store, _event_store, _workspace_service = runner_env
    sentinel = object()
    runner._search_service = sentinel  # noqa: SLF001

    class FakeActor:
        captured_search_service = None

        def __init__(self, **kwargs):  # noqa: ANN003
            type(self).captured_search_service = kwargs.get("search_service")
            self.inbox = asyncio.Queue()
            self._running = False
            self._last_active = 0.0

        @property
        def last_active(self) -> float:
            return self._last_active

        @property
        def is_running(self) -> bool:
            return self._running

        def start(self) -> None:
            self._running = True

        async def stop(self) -> None:
            self._running = False

    monkeypatch.setattr("remora.core.agents.runner.Actor", FakeActor)

    actor = runner.get_or_create_actor("agent-search")
    assert actor is not None
    assert FakeActor.captured_search_service is sentinel


@pytest.mark.asyncio
async def test_runner_evict_idle_uses_config_timeout(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "runner-timeout.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        infra=InfraConfig(workspace_root=".remora-runner-timeout"),
        runtime=RuntimeConfig(actor_idle_timeout_s=1.0),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config)

    try:
        actor = runner.get_or_create_actor("idle-timeout-agent")
        actor._last_active = time.time() - 2.0
        await runner._evict_idle()
        assert "idle-timeout-agent" not in runner.actors
    finally:
        await runner.stop_and_wait()
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_runner_drop_new_policy_caps_queue_and_drops_newest(tmp_path: Path) -> None:
    """drop_new policy should keep queue length capped and drop newest event."""
    db = await open_database(tmp_path / "runner-drop-new.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        infra=InfraConfig(workspace_root=".remora-runner-drop-new"),
        runtime=RuntimeConfig(
            actor_inbox_max_items=3,
            actor_inbox_overflow_policy=OverflowPolicy.DROP_NEW,
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config)

    try:
        actor = runner.get_or_create_actor("drop-new-agent")
        events = [
            AgentMessageEvent(from_agent="a", to_agent="drop-new-agent", content=f"msg-{i}")
            for i in range(5)
        ]

        for event in events:
            runner._route_to_actor("drop-new-agent", event)

        # Queue should be capped at max_items
        assert actor.inbox.qsize() <= config.runtime.actor_inbox_max_items

        # Should have first 3 events (oldest), dropped 2 newest
        assert actor.inbox.qsize() == 3
        queued_contents = [queued_event.content for queued_event in list(actor.inbox._queue)]
        assert queued_contents == ["msg-0", "msg-1", "msg-2"]
    finally:
        await runner.stop_and_wait()
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_runner_drop_oldest_policy_caps_queue_and_evicts_earliest(tmp_path: Path) -> None:
    """drop_oldest policy should keep queue length capped and evict earliest event."""
    db = await open_database(tmp_path / "runner-drop-oldest.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    config = Config(
        infra=InfraConfig(workspace_root=".remora-runner-drop-oldest"),
        runtime=RuntimeConfig(
            actor_inbox_max_items=3,
            actor_inbox_overflow_policy=OverflowPolicy.DROP_OLDEST,
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config)

    try:
        actor = runner.get_or_create_actor("drop-oldest-agent")
        events = [
            AgentMessageEvent(from_agent="a", to_agent="drop-oldest-agent", content=f"msg-{i}")
            for i in range(5)
        ]

        for event in events:
            runner._route_to_actor("drop-oldest-agent", event)

        # Queue should be capped at max_items
        assert actor.inbox.qsize() <= config.runtime.actor_inbox_max_items

        # Should have last 3 events (newest), dropped 2 oldest
        assert actor.inbox.qsize() == 3
        queued_contents = [queued_event.content for queued_event in list(actor.inbox._queue)]
        assert queued_contents == ["msg-2", "msg-3", "msg-4"]
    finally:
        await runner.stop_and_wait()
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_runner_reject_policy_caps_queue_and_increments_metrics(tmp_path: Path) -> None:
    """reject policy should keep queue length capped and increment reject metrics."""
    from remora.core.services.metrics import Metrics

    db = await open_database(tmp_path / "runner-reject.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    metrics = Metrics()
    config = Config(
        infra=InfraConfig(workspace_root=".remora-runner-reject"),
        runtime=RuntimeConfig(
            actor_inbox_max_items=3,
            actor_inbox_overflow_policy=OverflowPolicy.REJECT,
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config, metrics=metrics)

    try:
        actor = runner.get_or_create_actor("reject-agent")
        events = [
            AgentMessageEvent(from_agent="a", to_agent="reject-agent", content=f"msg-{i}")
            for i in range(5)
        ]

        for event in events:
            runner._route_to_actor("reject-agent", event)

        # Queue should be capped at max_items
        assert actor.inbox.qsize() <= config.runtime.actor_inbox_max_items

        # Should have first 3 events, rejected 2
        assert actor.inbox.qsize() == 3
        assert metrics.actor_inbox_overflow_total == 2
        assert metrics.actor_inbox_rejected_total == 2
        assert metrics.actor_inbox_dropped_new_total == 0
        assert metrics.actor_inbox_dropped_oldest_total == 0
    finally:
        await runner.stop_and_wait()
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_runner_overflow_metrics_all_policies(tmp_path: Path) -> None:
    """Verify overflow counters are incremented correctly for all policies."""
    from remora.core.services.metrics import Metrics

    for policy in OverflowPolicy:
        db = await open_database(tmp_path / f"runner-{policy.value}.db")
        node_store = NodeStore(db)
        await node_store.create_tables()
        event_store = EventStore(db=db)
        await event_store.create_tables()
        metrics = Metrics()
        config = Config(
            infra=InfraConfig(workspace_root=f".remora-runner-{policy.value}"),
            runtime=RuntimeConfig(
                actor_inbox_max_items=2,
                actor_inbox_overflow_policy=policy,
            ),
        )
        workspace_service = CairnWorkspaceService(config, tmp_path)
        await workspace_service.initialize()
        runner = ActorPool(event_store, node_store, workspace_service, config, metrics=metrics)

        try:
            actor = runner.get_or_create_actor(f"{policy.value}-agent")
            events = [
                AgentMessageEvent(
                    from_agent="a", to_agent=f"{policy.value}-agent", content=f"msg-{i}"
                )
                for i in range(5)
            ]

            for event in events:
                runner._route_to_actor(f"{policy.value}-agent", event)

            # Verify queue never exceeds max
            assert actor.inbox.qsize() <= config.runtime.actor_inbox_max_items

            # Verify overflow counter was incremented
            assert metrics.actor_inbox_overflow_total == 3  # 5 events - 2 max = 3 overflow

            if policy == OverflowPolicy.DROP_NEW:
                assert metrics.actor_inbox_dropped_new_total == 3
            elif policy == OverflowPolicy.DROP_OLDEST:
                assert metrics.actor_inbox_dropped_oldest_total == 3
            elif policy == OverflowPolicy.REJECT:
                assert metrics.actor_inbox_rejected_total == 3

        finally:
            await runner.stop_and_wait()
            await workspace_service.close()
            await db.close()


@pytest.mark.asyncio
async def test_runner_synthetic_overload_never_exceeds_max(tmp_path: Path) -> None:
    """Synthetic overload test: queue never exceeds max during high-volume routing."""
    from remora.core.services.metrics import Metrics

    db = await open_database(tmp_path / "runner-overload.db")
    node_store = NodeStore(db)
    await node_store.create_tables()
    event_store = EventStore(db=db)
    await event_store.create_tables()
    metrics = Metrics()
    max_items = 5
    config = Config(
        infra=InfraConfig(workspace_root=".remora-runner-overload"),
        runtime=RuntimeConfig(
            actor_inbox_max_items=max_items,
            actor_inbox_overflow_policy=OverflowPolicy.DROP_NEW,
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config, metrics=metrics)

    try:
        actor = runner.get_or_create_actor("overload-agent")

        # Rapidly queue 100 events
        for i in range(100):
            event = AgentMessageEvent(from_agent="a", to_agent="overload-agent", content=f"msg-{i}")
            runner._route_to_actor("overload-agent", event)
            # Check after each event that we never exceeded max
            assert actor.inbox.qsize() <= max_items, f"Queue exceeded max at event {i}"

        # Final verification
        assert actor.inbox.qsize() <= max_items
        assert metrics.actor_inbox_overflow_total == 95  # 100 - 5 = 95 overflow
    finally:
        await runner.stop_and_wait()
        await workspace_service.close()
        await db.close()
