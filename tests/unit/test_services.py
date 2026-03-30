from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.model.config import Config
from remora.core.storage.db import open_database
from remora.core.services.container import RuntimeServices


class _DummySearchService:
    init_calls = 0
    close_calls = 0

    def __init__(self, config, project_root):  # noqa: ANN001, ANN204
        self.config = config
        self.project_root = project_root
        self.available = True

    async def initialize(self) -> None:
        type(self).init_calls += 1

    async def close(self) -> None:
        type(self).close_calls += 1


class _DummyReconciler:
    last_search_service = None
    last_language_registry = None
    last_subscription_manager = None
    last_tx = None

    def __init__(
        self,
        config,
        node_store,
        event_store,
        workspace_service,
        project_root,
        language_registry,
        subscription_manager,
        *,
        search_service=None,
        tx=None,
    ) -> None:
        del config, node_store, event_store, workspace_service, project_root
        self._running = False
        self.stop_task = None
        type(self).last_search_service = search_service
        type(self).last_language_registry = language_registry
        type(self).last_subscription_manager = subscription_manager
        type(self).last_tx = tx

    async def start(self, event_bus) -> None:  # noqa: ANN001
        del event_bus
        self._running = True

    def stop(self) -> None:
        self._running = False


class _DummyActorPool:
    last_search_service = None

    def __init__(
        self,
        event_store,
        node_store,
        workspace_service,
        config,
        *,
        dispatcher=None,
        metrics=None,
        search_service=None,
        broker=None,
    ) -> None:
        del event_store, node_store, workspace_service, config, dispatcher, metrics, broker
        type(self).last_search_service = search_service

    async def stop_and_wait(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_services_search_disabled(tmp_path: Path, monkeypatch) -> None:
    import remora.core.services.container as container_module

    monkeypatch.setattr("remora.code.reconciler.FileReconciler", _DummyReconciler)
    monkeypatch.setattr(container_module, "ActorPool", _DummyActorPool)

    db = await open_database(tmp_path / "services-disabled.db")
    services = RuntimeServices(Config(), tmp_path, db)
    await services.initialize()

    assert services.search_service is None
    assert _DummyReconciler.last_search_service is None
    assert _DummyActorPool.last_search_service is None
    assert _DummyReconciler.last_language_registry is not None
    assert _DummyReconciler.last_subscription_manager is not None
    assert _DummyReconciler.last_tx is services.tx

    await services.close()


@pytest.mark.asyncio
async def test_runtime_services_search_enabled(tmp_path: Path, monkeypatch) -> None:
    import remora.core.services.container as container_module

    _DummySearchService.init_calls = 0
    _DummySearchService.close_calls = 0
    monkeypatch.setattr(container_module, "SearchService", _DummySearchService)
    monkeypatch.setattr("remora.code.reconciler.FileReconciler", _DummyReconciler)
    monkeypatch.setattr(container_module, "ActorPool", _DummyActorPool)

    config = Config(search={"enabled": True, "mode": "remote"})
    db = await open_database(tmp_path / "services-enabled.db")
    services = RuntimeServices(config, tmp_path, db)
    await services.initialize()

    assert services.search_service is not None
    assert _DummySearchService.init_calls == 1
    assert _DummyReconciler.last_search_service is services.search_service
    assert _DummyActorPool.last_search_service is services.search_service

    await services.close()
    assert _DummySearchService.close_calls == 1
