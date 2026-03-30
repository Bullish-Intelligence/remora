"""Tests for cross-file edge extraction in the reconciler."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from tests.factories import write_bundle_templates, write_file

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.model.config import BehaviorConfig, Config, InfraConfig, ProjectConfig
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService


@pytest_asyncio.fixture
async def reconciler_edges_env(tmp_path: Path):
    db = await open_database(tmp_path / "reconciler-edges.db")
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

    config = Config(
        project=ProjectConfig(discovery_paths=("src",), discovery_languages=("python",)),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            query_search_paths=("@default",),
            bundle_search_paths=(str(bundles_root),),
        ),
        infra=InfraConfig(workspace_root=".remora-reconcile"),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    language_registry = LanguageRegistry.from_defaults()
    subscription_manager = SubscriptionManager(event_store, workspace_service)
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
    )

    yield reconciler, node_store, tmp_path

    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_reconcile_creates_import_edges(reconciler_edges_env) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(src_dir / "models.py", "class Config:\n    pass\n")
    write_file(
        src_dir / "zz_app.py",
        "from models import Config\n\ndef main():\n    return Config()\n",
    )

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    import_edges = [edge for edge in all_edges if edge.edge_type == "imports"]
    assert import_edges
    assert any("Config" in edge.to_id for edge in import_edges)


@pytest.mark.asyncio
async def test_reconcile_import_resolution_is_order_independent(reconciler_edges_env) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    # Ensure importer file sorts before import target file.
    write_file(
        src_dir / "a.py",
        "from b import B\n\nclass A(B):\n    pass\n",
    )
    write_file(
        src_dir / "b.py",
        "class B:\n    pass\n",
    )

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    import_edges = [edge for edge in all_edges if edge.edge_type == "imports"]
    inherits_edges = [edge for edge in all_edges if edge.edge_type == "inherits"]
    assert any("a.py::A" in edge.from_id and "b.py::B" in edge.to_id for edge in import_edges)
    assert any("a.py::A" in edge.from_id and "b.py::B" in edge.to_id for edge in inherits_edges)


@pytest.mark.asyncio
async def test_reconcile_backfills_imports_when_target_file_added_later(
    reconciler_edges_env,
) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(
        src_dir / "a.py",
        "from b import B\n\nclass A(B):\n    pass\n",
    )
    await reconciler.reconcile_cycle()

    edges_before = await node_store.list_all_edges()
    assert not any(
        edge.edge_type == "imports" and "b.py::B" in edge.to_id for edge in edges_before
    )
    assert not any(
        edge.edge_type == "inherits" and "b.py::B" in edge.to_id for edge in edges_before
    )

    write_file(src_dir / "b.py", "class B:\n    pass\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    edges_after = await node_store.list_all_edges()
    imports = [
        edge
        for edge in edges_after
        if edge.edge_type == "imports" and "a.py::A" in edge.from_id and "b.py::B" in edge.to_id
    ]
    inherits = [
        edge
        for edge in edges_after
        if edge.edge_type == "inherits" and "a.py::A" in edge.from_id and "b.py::B" in edge.to_id
    ]
    assert len(imports) == 1
    assert len(inherits) == 1


@pytest.mark.asyncio
async def test_reconcile_removes_semantic_edges_when_target_symbol_removed(
    reconciler_edges_env,
) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(src_dir / "a.py", "from b import B\n\nclass A(B):\n    pass\n")
    target = src_dir / "b.py"
    write_file(target, "class B:\n    pass\n")
    await reconciler.reconcile_cycle()

    initial_edges = await node_store.list_all_edges()
    assert any(edge.edge_type == "imports" and "b.py::B" in edge.to_id for edge in initial_edges)
    assert any(edge.edge_type == "inherits" and "b.py::B" in edge.to_id for edge in initial_edges)

    write_file(target, "class C:\n    pass\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    updated_edges = await node_store.list_all_edges()
    assert not any(
        edge.edge_type == "imports" and "b.py::B" in edge.to_id for edge in updated_edges
    )
    assert not any(
        edge.edge_type == "inherits" and "b.py::B" in edge.to_id for edge in updated_edges
    )
    assert any(edge.edge_type == "contains" for edge in updated_edges)


@pytest.mark.asyncio
async def test_reconcile_creates_inheritance_edges(reconciler_edges_env) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(src_dir / "base.py", "class Animal:\n    pass\n")
    write_file(src_dir / "dog.py", "class Dog(Animal):\n    pass\n")

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    inherits_edges = [edge for edge in all_edges if edge.edge_type == "inherits"]
    assert any("Dog" in edge.from_id and "Animal" in edge.to_id for edge in inherits_edges)


@pytest.mark.asyncio
async def test_reconcile_clears_stale_edges_on_rereconcile(reconciler_edges_env) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(src_dir / "models.py", "class Config:\n    pass\n")
    source = src_dir / "zz_app.py"
    write_file(source, "from models import Config\n\ndef main():\n    pass\n")
    await reconciler.reconcile_cycle()

    write_file(source, "def main():\n    pass\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    import_edges = [edge for edge in all_edges if edge.edge_type == "imports"]
    app_imports = [edge for edge in import_edges if "zz_app.py" in edge.from_id]
    assert app_imports == []


@pytest.mark.asyncio
async def test_reconcile_preserves_contains_edges(reconciler_edges_env) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(
        src_dir / "app.py",
        "class Foo:\n    def bar(self):\n        pass\n",
    )

    await reconciler.reconcile_cycle()

    all_edges = await node_store.list_all_edges()
    contains_edges = [edge for edge in all_edges if edge.edge_type == "contains"]
    assert contains_edges


@pytest.mark.asyncio
async def test_reconcile_does_not_duplicate_semantic_edges_across_repeated_cycles(
    reconciler_edges_env,
) -> None:
    reconciler, node_store, project_root = reconciler_edges_env
    src_dir = project_root / "src"

    write_file(src_dir / "a.py", "from b import B\n\nclass A(B):\n    pass\n")
    write_file(src_dir / "b.py", "class B:\n    pass\n")
    await reconciler.reconcile_cycle()

    for _ in range(3):
        await reconciler.reconcile_cycle()

    semantic_edges = [
        (edge.from_id, edge.to_id, edge.edge_type)
        for edge in await node_store.list_all_edges()
        if edge.edge_type in {"imports", "inherits"}
    ]
    assert semantic_edges
    assert len(semantic_edges) == len(set(semantic_edges))
    assert semantic_edges.count(
        next(
            edge
            for edge in semantic_edges
            if "a.py::A" in edge[0] and "b.py::B" in edge[1] and edge[2] == "imports"
        )
    ) == 1
    assert semantic_edges.count(
        next(
            edge
            for edge in semantic_edges
            if "a.py::A" in edge[0] and "b.py::B" in edge[1] and edge[2] == "inherits"
        )
    ) == 1
