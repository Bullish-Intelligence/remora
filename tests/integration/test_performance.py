from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pytest
from tests.factories import make_node

from remora.code.discovery import discover
from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.model.config import (
    BehaviorConfig,
    Config,
    InfraConfig,
    ProjectConfig,
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
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService


def make_perf_node(idx: int):
    name = f"f{idx}"
    return make_node(
        f"src/perf.py::{name}",
        file_path="src/perf.py",
        start_line=idx + 1,
        end_line=idx + 1,
        text=f"def {name}():\n    return {idx}\n",
    )


@pytest.mark.asyncio
async def test_perf_discovery_100_nodes(tmp_path: Path) -> None:
    file_path = tmp_path / "src" / "perf.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    source = "\n".join(f"def f{i}():\n    return {i}\n" for i in range(120))
    file_path.write_text(source, encoding="utf-8")

    registry = LanguageRegistry.from_defaults()
    started = time.perf_counter()
    nodes = discover(
        [tmp_path / "src"],
        languages=["python"],
        language_registry=registry,
        language_map={".py": "python"},
    )
    elapsed = time.perf_counter() - started

    functions = [node for node in nodes if node.node_type == "function"]
    assert len(functions) >= 100
    assert elapsed < 5.0


@pytest.mark.asyncio
async def test_perf_nodestore_100_upserts(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "perf-nodes.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    node_store = NodeStore(db, tx=tx)
    await node_store.create_tables()

    started = time.perf_counter()
    for idx in range(100):
        await node_store.upsert_node(make_perf_node(idx))
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    await db.close()


@pytest.mark.asyncio
async def test_perf_subscription_matching(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "perf-subs.db")
    registry = SubscriptionRegistry(db)
    await registry.create_tables()

    for idx in range(100):
        await registry.register(
            f"agent-{idx}",
            SubscriptionPattern(to_agent=f"agent-{idx}"),
        )

    event = AgentMessageEvent(from_agent="user", to_agent="agent-42", content="ping")
    started = time.perf_counter()
    for _ in range(1000):
        matched = await registry.get_matching_agents(event)
    elapsed = time.perf_counter() - started

    assert "agent-42" in matched
    assert elapsed < 1.0
    await db.close()


@pytest.mark.asyncio
async def test_perf_reconciler_load_1000_files_10_nodes_each(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src_root = tmp_path / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    for file_idx in range(1000):
        lines = [
            f"def f_{file_idx}_{fn_idx}():\n    return {file_idx + fn_idx}\n"
            for fn_idx in range(10)
        ]
        (src_root / f"module_{file_idx:04d}.py").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )

    db = await open_database(tmp_path / "perf-reconciler.db")
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
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            languages={"python": {"extensions": [".py"]}},
            query_search_paths=("@default",),
        ),
        infra=InfraConfig(workspace_root=".remora-perf-reconciler"),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()

    async def _noop_provision_bundle(_node_id: str, _template_dirs: list[Path]) -> None:
        return None

    # Keep the load test focused on reconcile projection/storage behavior.
    monkeypatch.setattr(workspace_service, "provision_bundle", _noop_provision_bundle)

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
        tracemalloc.start()
        started = time.perf_counter()
        nodes = await reconciler.full_scan()
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        functions = [node for node in nodes if node.node_type == "function"]
        assert len(functions) >= 10_000
        assert elapsed < 90.0
        assert peak < 1_000_000_000
    finally:
        await workspace_service.close()
        await db.close()
