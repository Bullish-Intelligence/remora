"""Runtime service container for dependency injection."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from remora.core.agents.runner import ActorPool
from remora.core.events import EventBus, EventStore, SubscriptionRegistry, TriggerDispatcher
from remora.core.model.config import Config, resolve_query_search_paths
from remora.core.services.broker import HumanInputBroker
from remora.core.services.metrics import Metrics
from remora.core.services.search import SearchService, SearchServiceProtocol
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService


class RuntimeServices:
    """Central container holding runtime services."""

    def __init__(self, config: Config, project_root: Path, db: aiosqlite.Connection):
        from remora.code.languages import LanguageRegistry
        from remora.code.subscriptions import SubscriptionManager

        self.config = config
        self.project_root = project_root.resolve()
        self.db = db

        self.metrics = Metrics()
        self.human_input_broker = HumanInputBroker()
        self.event_bus = EventBus()
        self.dispatcher = TriggerDispatcher()
        self.tx = TransactionContext(db, self.event_bus, self.dispatcher)
        self.subscriptions = SubscriptionRegistry(db, tx=self.tx)
        self.dispatcher.subscriptions = self.subscriptions
        self.node_store = NodeStore(db, tx=self.tx)
        self.event_store = EventStore(
            db=db,
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
            metrics=self.metrics,
            tx=self.tx,
        )

        self.workspace_service = CairnWorkspaceService(config, project_root, metrics=self.metrics)
        self.language_registry = LanguageRegistry.from_config(
            language_defs=config.behavior.languages,
            query_search_paths=resolve_query_search_paths(config, project_root),
        )

        self.search_service: SearchServiceProtocol | None = None
        self.reconciler = None
        self.runner = None
        self._subscription_manager = SubscriptionManager

    async def initialize(self) -> None:
        """Create tables and initialize services."""
        from remora.code.reconciler import FileReconciler

        await self.node_store.create_tables()
        await self.event_store.create_tables()
        await self.workspace_service.initialize()

        if self.config.search.enabled:
            self.search_service = SearchService(self.config.search, self.project_root)
            await self.search_service.initialize()

        subscription_manager = self._subscription_manager(self.event_store, self.workspace_service)

        self.reconciler = FileReconciler(
            self.config,
            self.node_store,
            self.event_store,
            self.workspace_service,
            self.project_root,
            self.language_registry,
            subscription_manager,
            search_service=self.search_service,
            tx=self.tx,
        )
        await self.reconciler.start(self.event_bus)

        self.runner = ActorPool(
            self.event_store,
            self.node_store,
            self.workspace_service,
            self.config,
            dispatcher=self.dispatcher,
            metrics=self.metrics,
            search_service=self.search_service,
            broker=self.human_input_broker,
        )

    async def close(self) -> None:
        """Shut down all services."""
        if self.reconciler is not None:
            self.reconciler.stop()
            stop_task = self.reconciler.stop_task
            if stop_task is not None:
                try:
                    await stop_task
                except asyncio.CancelledError:
                    pass
        if self.runner is not None:
            await self.runner.stop_and_wait()
        if self.search_service is not None:
            await self.search_service.close()
        await self.workspace_service.close()
        await self.db.close()


__all__ = ["RuntimeServices"]
