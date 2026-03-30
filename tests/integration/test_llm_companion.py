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

_COMPANION_SYSTEM_PROMPT = (
    "You are the companion observer. When you receive a turn digest,\n"
    "call aggregate_digest exactly once with:\n"
    "- agent_id: the agent that completed the turn\n"
    "- summary: the digest summary\n"
    "- tags: comma-separated tags from the digest\n"
    "- insight: one short observation\n"
    "Then respond with one sentence."
)


def _write_companion_bundles(root: Path, model_name: str) -> None:
    for bundle_name in ("system", "companion", "code-agent"):
        shutil.copytree(DEFAULTS_BUNDLES / bundle_name, root / bundle_name)

    companion_bundle = root / "companion" / "bundle.yaml"
    data = yaml.safe_load(companion_bundle.read_text(encoding="utf-8"))
    data["model"] = model_name
    data["system_prompt"] = _COMPANION_SYSTEM_PROMPT
    data["max_turns"] = 4
    companion_bundle.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def _setup_companion_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
) -> tuple[Actor, EventStore, CairnWorkspaceService, aiosqlite.Connection]:
    write_file(
        tmp_path / "src" / "app.py",
        "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n",
    )
    bundles_root = tmp_path / "bundles"
    _write_companion_bundles(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-companion.db")
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
                "id": "companion",
                "role": "companion",
                "subscriptions": (
                    {
                        "event_types": ["turn_digested"],
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
    await reconciler.full_scan()

    companion = await node_store.get_node("companion")
    assert companion is not None
    actor = Actor(
        node_id=companion.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return actor, event_store, workspace_service, db


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_companion_aggregate_digest_stores_activity(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = event_store = workspace_service = db = None
    try:
        actor, event_store, workspace_service, db = await _setup_companion_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
        )

        correlation_id = "corr-companion-aggregate-one"
        trigger_event = AgentMessageEvent(
            from_agent="src/app.py::alpha",
            to_agent="companion",
            content=(
                "Turn digest: "
                "agent_id=src/app.py::alpha; "
                "summary=Explained the alpha function to user; "
                "tags=explanation,question"
            ),
            correlation_id=correlation_id,
        )
        outbox = Outbox(
            actor_id="companion",
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id="companion",
            correlation_id=correlation_id,
            event=trigger_event,
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=50)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        event_types = [entry["event_type"] for entry in by_corr]
        assert "agent_start" in event_types
        assert "agent_complete" in event_types
        assert "agent_error" not in event_types

        workspace = await workspace_service.get_agent_workspace("companion")
        activity_log = await workspace.kv_get("project/activity_log")
        assert isinstance(activity_log, list)
        assert len(activity_log) >= 1
        assert activity_log[-1]["agent_id"] == "src/app.py::alpha"

        tag_freq = await workspace.kv_get("project/tag_frequency")
        assert isinstance(tag_freq, dict)
        assert tag_freq.get("explanation", 0) > 0

        agent_activity = await workspace.kv_get("project/agent_activity")
        assert isinstance(agent_activity, dict)
        assert "src/app.py::alpha" in agent_activity
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_companion_multiple_digests_accumulate(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = event_store = workspace_service = db = None
    try:
        actor, event_store, workspace_service, db = await _setup_companion_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
        )

        digests = (
            (
                "corr-companion-aggregate-two-a",
                "src/app.py::alpha",
                "Reviewed alpha behavior for user question",
                "explanation,review",
            ),
            (
                "corr-companion-aggregate-two-b",
                "src/app.py::beta",
                "Discussed beta output constraints",
                "question,design",
            ),
        )
        for correlation_id, agent_id, summary, tags in digests:
            trigger_event = AgentMessageEvent(
                from_agent=agent_id,
                to_agent="companion",
                content=(
                    "Turn digest: "
                    f"agent_id={agent_id}; "
                    f"summary={summary}; "
                    f"tags={tags}"
                ),
                correlation_id=correlation_id,
            )
            outbox = Outbox(
                actor_id="companion",
                event_store=event_store,
                correlation_id=correlation_id,
            )
            trigger = Trigger(
                node_id="companion",
                correlation_id=correlation_id,
                event=trigger_event,
            )
            await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=80)
        for correlation_id, *_ in digests:
            by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
            assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
            assert not any(entry["event_type"] == "agent_error" for entry in by_corr)

        workspace = await workspace_service.get_agent_workspace("companion")
        activity_log = await workspace.kv_get("project/activity_log")
        assert isinstance(activity_log, list)
        assert len(activity_log) >= 2
        recent_agent_ids = [item["agent_id"] for item in activity_log[-2:]]
        assert "src/app.py::alpha" in recent_agent_ids
        assert "src/app.py::beta" in recent_agent_ids

        agent_activity = await workspace.kv_get("project/agent_activity")
        assert isinstance(agent_activity, dict)
        assert "src/app.py::alpha" in agent_activity
        assert "src/app.py::beta" in agent_activity
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
