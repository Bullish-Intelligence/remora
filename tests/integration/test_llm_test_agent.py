from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import aiosqlite
import pytest
import yaml
from tests.factories import write_file

from remora.code.languages import LanguageRegistry
from remora.code.reconciler import FileReconciler
from remora.code.subscriptions import SubscriptionManager
from remora.core.agents.actor import Actor, Outbox, Trigger
from remora.core.events import (
    AgentMessageEvent,
    EventBus,
    EventStore,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.model.config import (
    BehaviorConfig,
    Config,
    InfraConfig,
    ProjectConfig,
)
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService

DEFAULT_TEST_MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"
DEFAULTS_BUNDLES = Path("src/remora/defaults/bundles")
_REAL_LLM_ENV_MISSING = not os.getenv("REMORA_TEST_MODEL_URL")
_REAL_LLM_SKIP_REASON = "REMORA_TEST_MODEL_URL not set - skipping real LLM integration test"
pytestmark = pytest.mark.real_llm

_LLM_USER_TEMPLATE = (
    "# Node: {node_full_name}\n"
    "Type: {node_type} | File: {file_path}\n\n"
    "## Source Code\n"
    "```\n"
    "{source}\n"
    "```\n\n"
    "## Trigger\n"
    "Event: {event_type}\n"
    "Content: {event_content}\n"
)


def _write_test_agent_bundles(
    root: Path,
    model_name: str,
    system_prompt: str,
    reactive_prompt: str,
) -> None:
    for bundle_name in ("system", "test-agent", "code-agent"):
        shutil.copytree(DEFAULTS_BUNDLES / bundle_name, root / bundle_name)

    bundle_path = root / "test-agent" / "bundle.yaml"
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    data["model"] = model_name
    data["system_prompt"] = system_prompt
    data["max_turns"] = 6
    prompts = data.get("prompts") or {}
    prompts["reactive"] = reactive_prompt
    data["prompts"] = prompts
    bundle_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def _setup_test_agent_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
    system_prompt: str,
    reactive_prompt: str,
) -> tuple[
    Actor,
    EventStore,
    CairnWorkspaceService,
    aiosqlite.Connection,
    str,
]:
    write_file(
        tmp_path / "src" / "app.py",
        "def alpha(value: int) -> int:\n    return value + 1\n",
    )
    bundles_root = tmp_path / "bundles"
    _write_test_agent_bundles(
        bundles_root,
        model_name,
        system_prompt,
        reactive_prompt,
    )

    db = await open_database(tmp_path / "llm-test-agent.db")
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
            bundle_search_paths=(str(bundles_root),),
            bundle_overlays={
                "function": "code-agent",
                "class": "code-agent",
                "method": "code-agent",
            },
            prompt_templates={"user": _LLM_USER_TEMPLATE},
            model_default=model_name,
            max_turns=8,
        ),
        infra=InfraConfig(
            workspace_root=".remora-llm-int",
            model_base_url=model_url,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
        ),
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
    nodes = await reconciler.full_scan()
    target_node = next(
        (
            candidate
            for candidate in nodes
            if candidate.node_type == "function" and candidate.name == "alpha"
        ),
        None,
    )
    assert target_node is not None

    virtual_agent = await node_store.get_node("test-agent")
    assert virtual_agent is not None
    actor = Actor(
        node_id=virtual_agent.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return actor, event_store, workspace_service, db, target_node.node_id


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_test_agent_suggests_tests_for_node(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))
    target_node_id = f"{tmp_path / 'src' / 'app.py'}::alpha"

    system_prompt = (
        "You are a test scaffolding agent. When triggered:\n"
        f"1. Call suggest_tests with node_id='{target_node_id}'.\n"
        "2. Respond with one sentence summarizing suggestions.\n"
        "Do not call other tools."
    )
    reactive_prompt = (
        "Reactive trigger detected.\n"
        f"Call suggest_tests for node_id {target_node_id}.\n"
        "Then respond in one sentence."
    )

    actor = event_store = workspace_service = db = discovered_node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            discovered_node_id,
        ) = await _setup_test_agent_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            reactive_prompt=reactive_prompt,
        )

        correlation_id = "corr-test-agent-suggest"
        outbox = Outbox(
            actor_id="test-agent",
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id="test-agent",
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="runtime-observer",
                to_agent="test-agent",
                content=f"Reactive request: call suggest_tests for node_id={discovered_node_id}.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=80)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "suggest_tests"
            and not entry["payload"].get("is_error")
            for entry in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_test_agent_scaffolds_test(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))
    target_node_id = f"{tmp_path / 'src' / 'app.py'}::alpha"

    system_prompt = (
        "You are a test scaffolding agent. When triggered:\n"
        f"1. Call scaffold_test with node_id='{target_node_id}' and test_type='unit'.\n"
        "2. Reply with one sentence.\n"
        "Do not call other tools."
    )
    reactive_prompt = (
        "Reactive trigger detected.\n"
        f"Call scaffold_test for node_id {target_node_id} with test_type unit.\n"
        "Then respond in one sentence."
    )

    actor = event_store = workspace_service = db = discovered_node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            discovered_node_id,
        ) = await _setup_test_agent_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            reactive_prompt=reactive_prompt,
        )

        correlation_id = "corr-test-agent-scaffold"
        outbox = Outbox(
            actor_id="test-agent",
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id="test-agent",
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="runtime-observer",
                to_agent="test-agent",
                content=(
                    "Reactive request: call scaffold_test "
                    f"for node_id={discovered_node_id} with test_type=unit."
                ),
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=100)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)

        scaffold_events = [
            entry for entry in by_corr if entry["event_type"] == "ScaffoldRequestEvent"
        ]
        assert scaffold_events
        assert scaffold_events[0]["payload"]["intent"].startswith("Create unit tests")
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
