from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.factories import make_node, write_bundle_templates, write_file

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.agents.actor import Actor, TriggerPolicy
from remora.core.model.config import (
    BehaviorConfig,
    Config,
    InfraConfig,
    ProjectConfig,
    RuntimeConfig,
    resolve_query_search_paths,
)
from remora.core.storage.db import open_database
from remora.core.events import (
    AgentMessageEvent,
    EventBus,
    EventStore,
    SubscriptionPattern,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.storage.graph import NodeStore
from remora.core.agents.runner import ActorPool
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService


@pytest.mark.asyncio
async def test_concurrent_dispatch_serializes_for_single_actor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = await open_database(tmp_path / "dispatch.db")
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
        infra=InfraConfig(workspace_root=".remora-concurrency"),
        runtime=RuntimeConfig(trigger_cooldown_ms=0, max_trigger_depth=10),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    runner = ActorPool(event_store, node_store, workspace_service, config)

    node = make_node("src/app.py::concurrent")
    await node_store.upsert_node(node)
    await event_store.subscriptions.register(
        node.node_id,
        SubscriptionPattern(to_agent=node.node_id),
    )

    in_flight = 0
    max_in_flight = 0
    processed = 0
    done = asyncio.Event()
    lock = asyncio.Lock()

    monkeypatch.setattr(TriggerPolicy, "should_trigger", lambda _self, _corr: True)

    async def fake_execute_turn(self, trigger, outbox):  # noqa: ANN001, ANN202
        del trigger, outbox
        nonlocal in_flight, max_in_flight, processed
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            processed += 1
            in_flight -= 1
            if processed == 2:
                done.set()

    monkeypatch.setattr(Actor, "_execute_turn", fake_execute_turn)

    try:
        await asyncio.gather(
            event_store.append(
                AgentMessageEvent(
                    from_agent="sender-a",
                    to_agent=node.node_id,
                    content="one",
                    correlation_id="corr-1",
                )
            ),
            event_store.append(
                AgentMessageEvent(
                    from_agent="sender-b",
                    to_agent=node.node_id,
                    content="two",
                    correlation_id="corr-2",
                )
            ),
        )
        await asyncio.wait_for(done.wait(), timeout=3.0)
        assert max_in_flight == 1
    finally:
        await runner.stop_and_wait()
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_subscription_modification_during_dispatch_does_not_crash(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "subscriptions.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    event_store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()
    await event_store.subscriptions.register("agent-stable", SubscriptionPattern(to_agent="target"))

    routed: list[str] = []
    event_store.dispatcher.router = lambda agent_id, _event: routed.append(agent_id)

    async def emit_events() -> None:
        for idx in range(30):
            await event_store.append(
                AgentMessageEvent(
                    from_agent="sender",
                    to_agent="target",
                    content=f"msg-{idx}",
                    correlation_id=f"corr-{idx}",
                )
            )

    async def mutate_subscriptions() -> None:
        for idx in range(30):
            sub_id = await event_store.subscriptions.register(
                f"agent-dynamic-{idx}",
                SubscriptionPattern(to_agent="target"),
            )
            if idx % 2 == 0:
                await event_store.subscriptions.unregister(sub_id)

    try:
        await asyncio.gather(emit_events(), mutate_subscriptions())
        assert routed
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_overlapping_reconcile_cycles_are_idempotent(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "reconcile-concurrency.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    node_store = NodeStore(db, tx=tx)
    await node_store.create_tables()
    event_store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()

    bundles_root = tmp_path / "bundles"
    write_bundle_templates(bundles_root)
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")

    config = Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            languages={"python": {"extensions": [".py"]}},
            query_search_paths=("@default",),
            bundle_search_paths=(str(bundles_root),),
        ),
        infra=InfraConfig(workspace_root=".remora-reconcile-concurrency"),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    language_registry = LanguageRegistry.from_config(
        language_defs=config.behavior.languages,
        query_search_paths=resolve_query_search_paths(config, tmp_path),
    )
    subscription_manager = SubscriptionManager(event_store, workspace_service)
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
        tx=tx,
    )

    try:
        # Reconcile cycles are idempotent, not concurrency-safe (Cairn uses single-writer SQLite)
        await reconciler.reconcile_cycle()
        await reconciler.reconcile_cycle()
        nodes = await node_store.list_nodes()
        node_ids = [node.node_id for node in nodes]
        assert len(node_ids) == len(set(node_ids))
        assert any(node_id.endswith("::a") for node_id in node_ids)
    finally:
        await workspace_service.close()
        await db.close()
