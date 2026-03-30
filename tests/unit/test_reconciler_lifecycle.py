from __future__ import annotations

from pathlib import Path

import pytest
from tests.factories import write_bundle_templates

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.events import ContentChangedEvent, EventStore
from remora.core.model.config import BehaviorConfig, Config, InfraConfig, ProjectConfig
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.workspace import CairnWorkspaceService


@pytest.mark.asyncio
async def test_reconciler_start_is_idempotent(tmp_path: Path) -> None:
    """Calling start(event_bus) twice should not duplicate handling."""
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

    db = await open_database(tmp_path / "reconciler-idempotent.db")
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

    try:
        reconciler = FileReconciler(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root=tmp_path,
            language_registry=language_registry,
            subscription_manager=subscription_manager,
        )

        # Track reconcile calls
        reconcile_calls: list[str] = []

        async def mock_reconcile(event: ContentChangedEvent) -> None:
            reconcile_calls.append(event.path)

        # Replace _on_content_changed to count calls
        reconciler._on_content_changed = mock_reconcile

        await reconciler.start(event_bus)
        await reconciler.start(event_bus)  # Second start should be no-op

        # Emit event
        event = ContentChangedEvent(
            path=str(tmp_path / "src" / "test.py"),
            change_type="modified",
            agent_id="test",
            old_hash="old",
            new_hash="new",
        )
        await event_bus.emit(event)

        # Should have exactly one reconcile call
        assert len(reconcile_calls) == 1

    finally:
        reconciler.stop()
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_reconciler_stop_unsubscribes_content_changed(tmp_path: Path) -> None:
    """Calling stop() should unsubscribe the content-change handler."""
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

    db = await open_database(tmp_path / "reconciler-stop.db")
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

    try:
        reconciler = FileReconciler(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root=tmp_path,
            language_registry=language_registry,
            subscription_manager=subscription_manager,
        )

        reconcile_calls: list[str] = []

        async def mock_reconcile(event: ContentChangedEvent) -> None:
            reconcile_calls.append(event.path)

        reconciler._on_content_changed = mock_reconcile

        await reconciler.start(event_bus)
        reconciler.stop()

        # Emit event after stop
        event = ContentChangedEvent(
            path=str(tmp_path / "src" / "test.py"),
            change_type="modified",
            agent_id="test",
            old_hash="old",
            new_hash="new",
        )
        await event_bus.emit(event)

        # Should have zero reconcile calls
        assert len(reconcile_calls) == 0

    finally:
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
async def test_reconciler_start_after_stop_re_subscribes(tmp_path: Path) -> None:
    """Calling start() after stop() should re-subscribe exactly once."""
    from remora.core.events import EventBus, SubscriptionRegistry
    from remora.core.events.dispatcher import TriggerDispatcher
    from remora.core.storage.transaction import TransactionContext

    db = await open_database(tmp_path / "reconciler-restart.db")
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

    try:
        reconciler = FileReconciler(
            config,
            node_store,
            event_store,
            workspace_service,
            project_root=tmp_path,
            language_registry=language_registry,
            subscription_manager=subscription_manager,
        )

        reconcile_calls: list[str] = []

        async def mock_reconcile(event: ContentChangedEvent) -> None:
            reconcile_calls.append(event.path)

        reconciler._on_content_changed = mock_reconcile

        await reconciler.start(event_bus)
        reconciler.stop()
        await reconciler.start(event_bus)

        # Emit event
        event = ContentChangedEvent(
            path=str(tmp_path / "src" / "test.py"),
            change_type="modified",
            agent_id="test",
            old_hash="old",
            new_hash="new",
        )
        await event_bus.emit(event)

        # Should have exactly one reconcile call
        assert len(reconcile_calls) == 1

    finally:
        reconciler.stop()
        await workspace_service.close()
        await db.close()
