from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from tests.factories import make_node, write_bundle_templates, write_file

import remora.code.reconciler as reconciler_module
from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.events import (
    AgentCompleteEvent,
    AgentMessageEvent,
    ContentChangedEvent,
    EventStore,
    NodeChangedEvent,
)
from remora.core.model.config import (
    BehaviorConfig,
    Config,
    InfraConfig,
    ProjectConfig,
)
from remora.core.model.errors import RemoraError
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import CairnWorkspaceService


@pytest_asyncio.fixture
async def reconcile_env(tmp_path: Path):
    db = await open_database(tmp_path / "reconcile.db")
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

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

    yield (
        node_store,
        event_store,
        workspace_service,
        config,
        reconciler,
        language_registry,
        subscription_manager,
    )

    await workspace_service.close()
    await db.close()


@pytest.mark.asyncio
async def test_full_scan_discovers_registers_and_emits(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")

    nodes = await reconciler.full_scan()
    stored = await node_store.list_nodes()
    events = await event_store.get_events(limit=20)
    discovered = [event for event in events if event["event_type"] == "node_discovered"]

    assert nodes
    assert stored
    assert len(discovered) == len(stored)
    assert any(node.node_type == "directory" and node.node_id == "." for node in stored)

    app_node = next(node for node in stored if node.node_id.endswith("::a"))
    assert app_node.parent_id == "src"

    for node in stored:
        message_event = AgentMessageEvent(
            from_agent="user",
            to_agent=node.node_id,
            content="hello",
        )
        matched_message = await event_store.subscriptions.get_matching_agents(message_event)
        assert node.node_id in matched_message

        if node.node_type == "directory":
            child_path = (
                "src/app.py" if node.file_path == "." else f"mock/{node.file_path}/child.py"
            )
            node_event = NodeChangedEvent(
                node_id=node.node_id,
                old_hash="old",
                new_hash="new",
                file_path=child_path,
            )
            matched_node_changed = await event_store.subscriptions.get_matching_agents(node_event)
            assert node.node_id in matched_node_changed

            content_event = ContentChangedEvent(path=child_path)
            matched_content = await event_store.subscriptions.get_matching_agents(content_event)
            assert node.node_id in matched_content


@pytest.mark.asyncio
async def test_reconcile_cycle_modified_file_only(
    reconcile_env,
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    first = tmp_path / "src" / "first.py"
    second = tmp_path / "src" / "second.py"
    write_file(first, "def first():\n    return 1\n")
    write_file(second, "def second():\n    return 2\n")
    await reconciler.full_scan()

    seen_files: list[Path] = []
    real_discover = reconciler_module.discover

    def wrapped_discover(paths, **kwargs):  # noqa: ANN001, ANN202
        seen_files.extend(paths)
        return real_discover(paths, **kwargs)

    monkeypatch.setattr(reconciler_module, "discover", wrapped_discover)

    write_file(second, "def second():\n    return 3\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    changed_calls = [path for path in seen_files if path.name == "second.py"]
    first_calls = [path for path in seen_files if path.name == "first.py"]
    assert changed_calls
    assert not first_calls


@pytest.mark.asyncio
async def test_reconciler_caches_query_path_resolution(
    reconcile_env,
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        config,
        _reconciler,
        language_registry,
        subscription_manager,
    ) = reconcile_env

    resolve_calls = 0
    real_resolve_query_paths = reconciler_module.resolve_query_paths

    def counting_resolve_query_paths(config_obj, project_root):  # noqa: ANN001, ANN202
        nonlocal resolve_calls
        resolve_calls += 1
        return real_resolve_query_paths(config_obj, project_root)

    monkeypatch.setattr(reconciler_module, "resolve_query_paths", counting_resolve_query_paths)

    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
    )

    assert resolve_calls == 1

    first = tmp_path / "src" / "first.py"
    second = tmp_path / "src" / "second.py"
    write_file(first, "def first():\n    return 1\n")
    write_file(second, "def second():\n    return 2\n")
    await reconciler.reconcile_cycle()

    write_file(second, "def second():\n    return 3\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    assert resolve_calls == 1


@pytest.mark.asyncio
async def test_reconcile_cycle_handles_new_and_deleted_files(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    file_a = tmp_path / "src" / "a.py"
    file_b = tmp_path / "src" / "b.py"
    write_file(file_a, "def a():\n    return 1\n")
    await reconciler.full_scan()

    write_file(file_b, "def b():\n    return 2\n")
    await reconciler.reconcile_cycle()
    assert await node_store.get_node(f"{file_b}::b") is not None

    file_a.unlink()
    await reconciler.reconcile_cycle()
    assert await node_store.get_node(f"{file_a}::a") is None

    events = await event_store.get_events(limit=50)
    removed = [event for event in events if event["event_type"] == "node_removed"]
    assert removed


@pytest.mark.asyncio
async def test_reconcile_subscription_idempotency(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()
    await reconciler.reconcile_cycle()
    await reconciler.reconcile_cycle()

    nodes = await node_store.list_nodes()
    for node in nodes:
        message_event = AgentMessageEvent(
            from_agent="test",
            to_agent=node.node_id,
            content="ping",
        )
        matched = await event_store.subscriptions.get_matching_agents(message_event)
        assert node.node_id in matched


@pytest.mark.asyncio
async def test_reconciler_stop_is_idempotent(reconcile_env) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env

    reconciler.stop()
    reconciler.stop()


@pytest.mark.asyncio
async def test_reconciler_survives_cycle_error(reconcile_env, tmp_path: Path, monkeypatch) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    source = tmp_path / "src" / "app.py"
    write_file(source, "def a():\n    return 1\n")

    call_count = 0

    async def fake_awatch(*_args, **_kwargs):  # noqa: ANN001, ANN202
        yield {(1, str(source))}
        yield {(1, str(source))}

    async def flaky_reconcile(_file_path: str, _mtime_ns: int, **_kwargs) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RemoraError("simulated failure")
        reconciler.stop()

    monkeypatch.setitem(sys.modules, "watchfiles", SimpleNamespace(awatch=fake_awatch))
    monkeypatch.setattr(reconciler, "_reconcile_file", flaky_reconcile)

    await asyncio.wait_for(reconciler.run_forever(), timeout=1.0)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_reconciler_watch_import_error_is_not_suppressed(reconcile_env, monkeypatch) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env

    async def fake_watch(_on_changes) -> None:  # noqa: ANN001
        raise ImportError("watchfiles unavailable")

    monkeypatch.setattr(reconciler._watcher, "watch", fake_watch)
    with pytest.raises(ImportError, match="watchfiles unavailable"):
        await asyncio.wait_for(reconciler.run_forever(), timeout=0.05)


@pytest.mark.asyncio
async def test_handle_watch_changes_refreshes_semantic_edges_order_independently(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    importer = tmp_path / "src" / "a.py"
    target = tmp_path / "src" / "b.py"
    write_file(importer, "from b import B\n\nclass A(B):\n    pass\n")
    write_file(target, "class B:\n    pass\n")

    await reconciler._handle_watch_changes({str(importer), str(target)})
    watch_semantic_edges = {
        (edge.from_id, edge.to_id, edge.edge_type)
        for edge in await node_store.list_all_edges()
        if edge.edge_type in {"imports", "inherits"}
    }

    assert any("a.py::A" in from_id and "b.py::B" in to_id and edge_type == "imports"
               for from_id, to_id, edge_type in watch_semantic_edges)
    assert any("a.py::A" in from_id and "b.py::B" in to_id and edge_type == "inherits"
               for from_id, to_id, edge_type in watch_semantic_edges)

    await reconciler.reconcile_cycle()
    cycle_semantic_edges = {
        (edge.from_id, edge.to_id, edge.edge_type)
        for edge in await node_store.list_all_edges()
        if edge.edge_type in {"imports", "inherits"}
    }
    assert cycle_semantic_edges == watch_semantic_edges


@pytest.mark.asyncio
async def test_handle_watch_changes_backfills_when_only_target_file_changes(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    importer = tmp_path / "src" / "a.py"
    target = tmp_path / "src" / "b.py"
    write_file(importer, "from b import B\n\nclass A(B):\n    pass\n")

    await reconciler._handle_watch_changes({str(importer)})
    edges_before = await node_store.list_all_edges()
    assert not any(edge.edge_type == "imports" and "b.py::B" in edge.to_id for edge in edges_before)

    write_file(target, "class B:\n    pass\n")
    await reconciler._handle_watch_changes({str(target)})

    edges_after = await node_store.list_all_edges()
    assert any(
        edge.edge_type == "imports"
        and "a.py::A" in edge.from_id
        and "b.py::B" in edge.to_id
        for edge in edges_after
    )
    assert any(
        edge.edge_type == "inherits"
        and "a.py::A" in edge.from_id
        and "b.py::B" in edge.to_id
        for edge in edges_after
    )


@pytest.mark.asyncio
async def test_reconciler_content_changed_event_triggers_reconcile(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    source_file = tmp_path / "src" / "event.py"
    write_file(source_file, "def event_fn():\n    return 1\n")
    await reconciler.full_scan()

    write_file(source_file, "def event_fn():\n    return 2\n")
    await reconciler._on_content_changed(
        ContentChangedEvent(path=str(source_file), change_type="modified")
    )

    node = await node_store.get_node(f"{source_file}::event_fn")
    assert node is not None
    assert "return 2" in node.text


@pytest.mark.asyncio
async def test_reconciler_content_changed_event_backfills_target_only_relationships(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    importer = tmp_path / "src" / "a.py"
    target = tmp_path / "src" / "b.py"
    write_file(importer, "from b import B\n\nclass A(B):\n    pass\n")
    await reconciler.full_scan()

    write_file(target, "class B:\n    pass\n")
    await reconciler._on_content_changed(
        ContentChangedEvent(path=str(target), change_type="modified")
    )

    edges = await node_store.list_all_edges()
    assert any(
        edge.edge_type == "imports"
        and "a.py::A" in edge.from_id
        and "b.py::B" in edge.to_id
        for edge in edges
    )
    assert any(
        edge.edge_type == "inherits"
        and "a.py::A" in edge.from_id
        and "b.py::B" in edge.to_id
        for edge in edges
    )


@pytest.mark.asyncio
async def test_reconciler_content_changed_ignores_paths_outside_discovery_roots(
    reconcile_env,
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    outside_file = tmp_path / "outside.py"
    write_file(outside_file, "def outside_fn():\n    return 1\n")

    called = False

    async def fake_reconcile(_file_path: str, _mtime_ns: int, **_kwargs) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(reconciler, "_reconcile_file", fake_reconcile)

    await reconciler._on_content_changed(
        ContentChangedEvent(path=str(outside_file), change_type="modified")
    )

    assert called is False


@pytest.mark.asyncio
async def test_file_lock_cache_evicts_unused_entries(reconcile_env, tmp_path: Path) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    file_a = tmp_path / "src" / "a.py"
    file_b = tmp_path / "src" / "b.py"
    write_file(file_a, "def a():\n    return 1\n")
    write_file(file_b, "def b():\n    return 1\n")

    await reconciler.reconcile_cycle()
    assert str(file_a) in reconciler._file_locks
    assert str(file_b) in reconciler._file_locks

    write_file(file_a, "def a():\n    return 2\n")
    await asyncio.sleep(0.001)
    await reconciler.reconcile_cycle()

    assert str(file_a) in reconciler._file_locks
    assert str(file_b) not in reconciler._file_locks


@pytest.mark.asyncio
async def test_file_lock_cache_caps_size_by_generation(reconcile_env, monkeypatch) -> None:
    (
        _node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env

    monkeypatch.setattr(reconciler, "_MAX_FILE_LOCKS", 2, raising=False)
    reconciler._file_locks = {
        "a.py": asyncio.Lock(),
        "b.py": asyncio.Lock(),
        "c.py": asyncio.Lock(),
    }
    reconciler._file_lock_generations = {
        "a.py": 1,
        "b.py": 2,
        "c.py": 3,
    }

    reconciler._evict_stale_file_locks(generation=0)

    assert len(reconciler._file_locks) == 2
    assert "a.py" not in reconciler._file_locks
    assert set(reconciler._file_locks) == {"b.py", "c.py"}


@pytest.mark.asyncio
async def test_reconciler_handles_malformed_source(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    bad_source = tmp_path / "src" / "broken.py"
    write_file(bad_source, "def broken(:\n    pass\n")

    await reconciler.reconcile_cycle()
    nodes = await node_store.list_nodes(file_path=str(bad_source))
    assert isinstance(nodes, list)


@pytest.mark.asyncio
async def test_directory_nodes_materialize_parent_chain(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        _event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    write_file(tmp_path / "src" / "pkg" / "mod.py", "def fn():\n    return 1\n")

    await reconciler.full_scan()
    root = await node_store.get_node(".")
    src_dir = await node_store.get_node("src")
    pkg_dir = await node_store.get_node("src/pkg")
    fn_node = await node_store.get_node(f"{tmp_path / 'src' / 'pkg' / 'mod.py'}::fn")

    assert root is not None
    assert root.node_type == "directory"
    assert root.parent_id is None
    assert src_dir is not None
    assert src_dir.parent_id == "."
    assert pkg_dir is not None
    assert pkg_dir.parent_id == "src"
    assert fn_node is not None
    assert fn_node.parent_id == "src/pkg"

    edges = await node_store.list_all_edges()
    contains_edges = {(edge.from_id, edge.to_id, edge.edge_type) for edge in edges}
    assert (".", "src", "contains") in contains_edges
    assert ("src", "src/pkg", "contains") in contains_edges
    assert ("src/pkg", fn_node.node_id, "contains") in contains_edges


@pytest.mark.asyncio
async def test_directory_nodes_removed_when_tree_disappears(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    source = tmp_path / "src" / "gone" / "leaf.py"
    write_file(source, "def leaf():\n    return 1\n")
    await reconciler.full_scan()
    pre_edges = {
        (edge.from_id, edge.to_id, edge.edge_type) for edge in await node_store.list_all_edges()
    }
    assert ("src", "src/gone", "contains") in pre_edges

    source.unlink()
    await reconciler.reconcile_cycle()

    assert await node_store.get_node("src/gone") is None
    post_edges = {
        (edge.from_id, edge.to_id, edge.edge_type) for edge in await node_store.list_all_edges()
    }
    assert ("src", "src/gone", "contains") not in post_edges
    events = await event_store.get_events(limit=50)
    removed_ids = [
        event["payload"]["node_id"] for event in events if event["event_type"] == "node_removed"
    ]
    assert "src/gone" in removed_ids


@pytest.mark.asyncio
async def test_directory_subscriptions_refreshed_on_startup(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        config,
        reconciler,
        language_registry,
        subscription_manager,
    ) = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    await event_store.subscriptions.unregister_by_agent(".")

    restart_reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
    )
    await restart_reconciler.reconcile_cycle()

    test_event = NodeChangedEvent(node_id=".", old_hash="x", new_hash="y", file_path="src/app.py")
    matched = await event_store.subscriptions.get_matching_agents(test_event)
    assert "." in matched


@pytest.mark.asyncio
async def test_directory_bundles_refreshed_on_startup(reconcile_env, tmp_path: Path) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        config,
        reconciler,
        language_registry,
        subscription_manager,
    ) = reconcile_env
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    await reconciler.full_scan()

    root_workspace = await workspace_service.get_agent_workspace(".")
    await root_workspace.write("_bundle/tools/send_message.pym", "result = 'stale'\nresult\n")

    system_tool = tmp_path / "bundles" / "system" / "tools" / "send_message.pym"
    system_tool.write_text("result = 'fresh'\nresult\n", encoding="utf-8")

    restart_reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
    )
    await restart_reconciler.reconcile_cycle()
    refreshed = await root_workspace.read("_bundle/tools/send_message.pym")
    assert "fresh" in refreshed


class _MockSearchService:
    def __init__(self, *, available: bool = True, fail_index: bool = False) -> None:
        self.available = available
        self.fail_index = fail_index
        self.indexed: list[str] = []
        self.deindexed: list[str] = []

    async def index_file(self, file_path: str) -> None:
        self.indexed.append(file_path)
        if self.fail_index:
            raise RemoraError("index failed")

    async def delete_source(self, file_path: str) -> None:
        self.deindexed.append(file_path)


@pytest.mark.asyncio
async def test_reconciler_indexes_files_when_search_service_available(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        config,
        _reconciler,
        language_registry,
        subscription_manager,
    ) = reconcile_env
    search = _MockSearchService(available=True)
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
        search_service=search,
    )
    source = tmp_path / "src" / "index_me.py"
    write_file(source, "def index_me():\n    return 1\n")

    await reconciler.full_scan()
    assert str(source) in search.indexed


@pytest.mark.asyncio
async def test_reconciler_deindexes_files_on_delete(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        config,
        _reconciler,
        language_registry,
        subscription_manager,
    ) = reconcile_env
    search = _MockSearchService(available=True)
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
        search_service=search,
    )
    source = tmp_path / "src" / "delete_me.py"
    write_file(source, "def delete_me():\n    return 1\n")
    await reconciler.full_scan()

    source.unlink()
    await reconciler.reconcile_cycle()
    assert str(source) in search.deindexed


@pytest.mark.asyncio
async def test_reconciler_search_index_failures_do_not_break_reconcile(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        config,
        _reconciler,
        language_registry,
        subscription_manager,
    ) = reconcile_env
    search = _MockSearchService(available=True, fail_index=True)
    reconciler = FileReconciler(
        config,
        node_store,
        event_store,
        workspace_service,
        project_root=tmp_path,
        language_registry=language_registry,
        subscription_manager=subscription_manager,
        search_service=search,
    )
    source = tmp_path / "src" / "fail_index.py"
    write_file(source, "def fail_index():\n    return 1\n")

    await reconciler.reconcile_cycle()
    node = await node_store.get_node(f"{source}::fail_index")
    assert node is not None


@pytest.mark.asyncio
async def test_self_reflect_subscription_registered(reconcile_env) -> None:
    (
        node_store,
        event_store,
        workspace_service,
        _config,
        reconciler,
        _language_registry,
        subscription_manager,
    ) = reconcile_env
    node = make_node("src/validate.py::validate", file_path="src/validate.py")
    await node_store.upsert_node(node)

    workspace = await workspace_service.get_agent_workspace(node.node_id)
    await workspace.kv_set("_system/self_reflect", {"enabled": True})

    await subscription_manager.register_for_node(node)

    event = AgentCompleteEvent(agent_id=node.node_id, tags=("primary",))
    matches = await event_store.subscriptions.get_matching_agents(event)
    assert node.node_id in matches


@pytest.mark.asyncio
async def test_no_self_reflect_subscription_when_disabled(reconcile_env) -> None:
    (
        node_store,
        event_store,
        _workspace_service,
        _config,
        reconciler,
        _language_registry,
        subscription_manager,
    ) = reconcile_env
    node = make_node("src/validate.py::validate", file_path="src/validate.py")
    await node_store.upsert_node(node)

    await subscription_manager.register_for_node(node)

    event = AgentCompleteEvent(agent_id=node.node_id, tags=("primary",))
    matches = await event_store.subscriptions.get_matching_agents(event)
    assert matches == []


@pytest.mark.asyncio
async def test_provision_bundle_persists_self_reflect_config(reconcile_env, tmp_path: Path) -> None:
    (
        _node_store,
        _event_store,
        workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    role_bundle = tmp_path / "bundles" / "code-agent" / "bundle.yaml"
    role_bundle.write_text(
        "name: code-agent\n"
        "self_reflect:\n"
        "  enabled: true\n"
        "  model: reflection-model\n"
        "  max_turns: 2\n"
        "  prompt: Reflect now\n",
        encoding="utf-8",
    )

    node_id = "src/app.py::self-reflect-node"
    await reconciler._provision_bundle(node_id, "code-agent")

    workspace = await workspace_service.get_agent_workspace(node_id)
    saved = await workspace.kv_get("_system/self_reflect")
    assert isinstance(saved, dict)
    assert saved["enabled"] is True
    assert saved["model"] == "reflection-model"


@pytest.mark.asyncio
async def test_provision_bundle_clears_self_reflect_when_disabled(
    reconcile_env,
    tmp_path: Path,
) -> None:
    (
        _node_store,
        _event_store,
        workspace_service,
        _config,
        reconciler,
        _language_registry,
        _subscription_manager,
    ) = reconcile_env
    role_bundle = tmp_path / "bundles" / "code-agent" / "bundle.yaml"
    role_bundle.write_text("name: code-agent\nself_reflect:\n  enabled: false\n", encoding="utf-8")

    node_id = "src/app.py::self-reflect-disabled-node"
    workspace = await workspace_service.get_agent_workspace(node_id)
    await workspace.kv_set("_system/self_reflect", {"enabled": True})

    await reconciler._provision_bundle(node_id, "code-agent")
    saved = await workspace.kv_get("_system/self_reflect")
    assert saved is None


@pytest.mark.asyncio
async def test_virtual_agents_bootstrapped_with_subscriptions(tmp_path: Path) -> None:
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

    db = await open_database(tmp_path / "virtual.db")
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
    write_bundle_templates(bundles_root, role="test-agent")

    config = Config(
        project=ProjectConfig(discovery_paths=("src",), discovery_languages=("python",)),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            query_search_paths=("@default",),
            bundle_search_paths=(str(bundles_root),),
        ),
        infra=InfraConfig(workspace_root=".remora-reconcile"),
        virtual_agents=(
            {
                "id": "test-agent",
                "role": "test-agent",
                "subscriptions": (
                    {
                        "event_types": ["node_changed"],
                        "path_glob": "src/**",
                    },
                ),
            },
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    language_registry = LanguageRegistry.from_defaults()
    subscription_manager = SubscriptionManager(event_store, workspace_service)

    try:
        write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
        reconciler = FileReconciler(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root=tmp_path,
            language_registry=language_registry,
            subscription_manager=subscription_manager,
        )
        await reconciler.full_scan()

        virtual = await node_store.get_node("test-agent")
        assert virtual is not None
        assert virtual.node_type == "virtual"
        assert virtual.role == "test-agent"
        assert virtual.file_path == ""
        assert virtual.text == ""

        matched = await event_store.subscriptions.get_matching_agents(
            NodeChangedEvent(
                node_id="src/app.py::a",
                old_hash="old",
                new_hash="new",
                file_path="src/app.py",
            )
        )
        assert "test-agent" in matched

        ws = await workspace_service.get_agent_workspace("test-agent")
        assert await ws.exists("_bundle/bundle.yaml")
    finally:
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_reconciler_handles_external_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    source_file = external_root / "pkg" / "outside.py"

    write_file(source_file, "def outside_fn():\n    return 1\n")

    db = await open_database(tmp_path / "external-paths.db")
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

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
        project=ProjectConfig(
            discovery_paths=(str(external_root),), discovery_languages=("python",)
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            query_search_paths=("@default",),
            bundle_search_paths=(str(bundles_root),),
        ),
        infra=InfraConfig(workspace_root=".remora-reconcile"),
    )
    workspace_service = CairnWorkspaceService(config, project_root)
    await workspace_service.initialize()
    language_registry = LanguageRegistry.from_defaults()
    subscription_manager = SubscriptionManager(event_store, workspace_service)

    try:
        reconciler = FileReconciler(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root=project_root,
            language_registry=language_registry,
            subscription_manager=subscription_manager,
        )
        await reconciler.reconcile_cycle()

        fn_node = await node_store.get_node(f"{source_file}::outside_fn")
        assert fn_node is not None
        assert fn_node.file_path == str(source_file)
        assert fn_node.parent_id == str(source_file.parent)
    finally:
        await workspace_service.close()
        await db.close()
