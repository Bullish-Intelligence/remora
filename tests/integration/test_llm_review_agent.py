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


def _write_review_agent_bundles(
    root: Path,
    model_name: str,
    system_prompt: str,
    reactive_prompt: str,
) -> None:
    for bundle_name in ("system", "review-agent", "code-agent"):
        shutil.copytree(DEFAULTS_BUNDLES / bundle_name, root / bundle_name)

    review_bundle = root / "review-agent" / "bundle.yaml"
    data = yaml.safe_load(review_bundle.read_text(encoding="utf-8"))
    data["model"] = model_name
    data["system_prompt"] = system_prompt
    data["max_turns"] = 6
    prompts = data.get("prompts") or {}
    prompts["reactive"] = reactive_prompt
    data["prompts"] = prompts
    review_bundle.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def _setup_review_runtime(
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
    FileReconciler,
    Path,
    str,
]:
    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    _write_review_agent_bundles(
        bundles_root,
        model_name,
        system_prompt,
        reactive_prompt,
    )

    db = await open_database(tmp_path / "llm-review-agent.db")
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
                "id": "review-agent",
                "role": "review-agent",
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

    review_agent = await node_store.get_node("review-agent")
    assert review_agent is not None
    actor = Actor(
        node_id=review_agent.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return (
        actor,
        event_store,
        workspace_service,
        db,
        reconciler,
        source_path,
        target_node.node_id,
    )


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_review_agent_reviews_node_change(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = event_store = workspace_service = db = reconciler = source_path = target_node_id = None
    try:
        expected_target_node_id = f"{tmp_path / 'src' / 'app.py'}::alpha"
        system_prompt = (
            "You are a strict tool-using review agent.\n"
            "For each reactive turn you MUST call tools in order and then stop.\n"
            "Required order:\n"
            "1) list_recent_changes\n"
            "2) review_diff(node_id='TARGET_NODE_ID')\n"
            "3) submit_review(node_id='TARGET_NODE_ID', "
            "finding='Initial review recorded', severity='info', notify_user=true)\n"
            "If you skip any call, the turn is invalid."
        )
        reactive_prompt = (
            "Reactive trigger detected.\n"
            "Execute exactly this sequence:\n"
            "- list_recent_changes\n"
            "- review_diff with node_id TARGET_NODE_ID\n"
            "- submit_review with notify_user=true\n"
            "Then reply with one sentence."
        )
        (
            actor,
            event_store,
            workspace_service,
            db,
            reconciler,
            source_path,
            target_node_id,
        ) = await _setup_review_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt.replace("TARGET_NODE_ID", expected_target_node_id),
            reactive_prompt=reactive_prompt.replace("TARGET_NODE_ID", expected_target_node_id),
        )
        del reconciler, source_path

        correlation_id = "corr-review-agent-a"
        outbox = Outbox(
            actor_id="review-agent",
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id="review-agent",
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="runtime-observer",
                to_agent="review-agent",
                content=(
                    "Reactive review task: call list_recent_changes, then call "
                    f"review_diff with node_id={target_node_id}, then call submit_review "
                    f"with node_id={target_node_id} and notify_user=true."
                ),
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=80)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        event_types = [entry["event_type"] for entry in by_corr]
        assert "agent_complete" in event_types
        assert "agent_error" not in event_types
        assert any(
            entry["event_type"] == "agent_message"
            and entry["payload"].get("to_agent") in {target_node_id, "user"}
            for entry in by_corr
        ), by_corr

        workspace = await workspace_service.get_agent_workspace("review-agent")
        keys = await workspace.kv_list(prefix="review:previous_source:")
        assert keys, "expected review_diff to persist previous_source state"
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_review_agent_detects_diff_on_second_review(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = event_store = workspace_service = db = reconciler = source_path = target_node_id = None
    try:
        expected_target_node_id = f"{tmp_path / 'src' / 'app.py'}::alpha"
        system_prompt = (
            "You are a strict diff checker.\n"
            "On every reactive turn, call review_diff exactly once with "
            "node_id='TARGET_NODE_ID'. Do not call other tools."
        )
        reactive_prompt = (
            "Reactive trigger detected.\n"
            "Call review_diff exactly once for node_id TARGET_NODE_ID.\n"
            "After the tool call, respond with one short sentence."
        )
        (
            actor,
            event_store,
            workspace_service,
            db,
            reconciler,
            source_path,
            target_node_id,
        ) = await _setup_review_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt.replace("TARGET_NODE_ID", expected_target_node_id),
            reactive_prompt=reactive_prompt.replace("TARGET_NODE_ID", expected_target_node_id),
        )

        first_corr = "corr-review-agent-b-first"
        first_outbox = Outbox(
            actor_id="review-agent",
            event_store=event_store,
            correlation_id=first_corr,
        )
        first_trigger = Trigger(
            node_id="review-agent",
            correlation_id=first_corr,
            event=AgentMessageEvent(
                from_agent="runtime-observer",
                to_agent="review-agent",
                content=f"Reactive review task: call review_diff for node_id={target_node_id}.",
                correlation_id=first_corr,
            ),
        )
        await actor._execute_turn(first_trigger, first_outbox)

        write_file(source_path, "def alpha():\n    return 99\n")
        await reconciler.full_scan()

        second_corr = "corr-review-agent-b-second"
        second_outbox = Outbox(
            actor_id="review-agent",
            event_store=event_store,
            correlation_id=second_corr,
        )
        second_trigger = Trigger(
            node_id="review-agent",
            correlation_id=second_corr,
            event=AgentMessageEvent(
                from_agent="runtime-observer",
                to_agent="review-agent",
                content=f"Reactive review task: call review_diff for node_id={target_node_id}.",
                correlation_id=second_corr,
            ),
        )
        await actor._execute_turn(second_trigger, second_outbox)

        events = await event_store.get_events(limit=120)
        first_events = [entry for entry in events if entry.get("correlation_id") == first_corr]
        second_events = [entry for entry in events if entry.get("correlation_id") == second_corr]
        assert any(entry["event_type"] == "agent_complete" for entry in first_events)
        assert not any(entry["event_type"] == "agent_error" for entry in first_events)
        assert any(entry["event_type"] == "agent_complete" for entry in second_events)
        assert not any(entry["event_type"] == "agent_error" for entry in second_events)

        workspace = await workspace_service.get_agent_workspace("review-agent")
        keys = await workspace.kv_list(prefix="review:previous_source:")
        assert keys, {
            "events": second_events,
            "all_by_corr": {
                "first": first_events,
                "second": second_events,
            },
        }
        target_key = f"review:previous_source:{target_node_id}"
        latest_source = await workspace.kv_get(target_key)
        assert isinstance(latest_source, str)
        assert "return 99" in latest_source
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
