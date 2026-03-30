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


def _write_directory_project(tmp_path: Path) -> None:
    write_file(tmp_path / "src" / "app.py", "def alpha():\n    return 1\n")
    write_file(tmp_path / "src" / "utils.py", "def beta():\n    return 2\n")
    write_file(tmp_path / "src" / "models" / "user.py", "class User:\n    pass\n")


def _write_directory_bundles(
    root: Path,
    model_name: str,
    system_prompt: str,
    chat_prompt: str,
) -> None:
    for bundle_name in ("system", "directory-agent", "code-agent"):
        shutil.copytree(DEFAULTS_BUNDLES / bundle_name, root / bundle_name)

    bundle_path = root / "directory-agent" / "bundle.yaml"
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    data["model"] = model_name
    data["system_prompt"] = system_prompt
    data["max_turns"] = 6
    prompts = data.get("prompts") or {}
    prompts["chat"] = chat_prompt
    data["prompts"] = prompts
    bundle_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def _setup_directory_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
    system_prompt: str,
    chat_prompt: str,
) -> tuple[Actor, EventStore, CairnWorkspaceService, aiosqlite.Connection, str]:
    _write_directory_project(tmp_path)
    bundles_root = tmp_path / "bundles"
    _write_directory_bundles(bundles_root, model_name, system_prompt, chat_prompt)

    db = await open_database(tmp_path / "llm-directory-agent.db")
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
                "directory": "directory-agent",
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
    src_directory = next(
        (
            candidate
            for candidate in nodes
            if candidate.node_type == "directory" and candidate.name == "src"
        ),
        None,
    )
    assert src_directory is not None

    actor = Actor(
        node_id=src_directory.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return actor, event_store, workspace_service, db, src_directory.node_id


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_directory_agent_list_children(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "You manage a directory. For each chat turn:\n"
        "1. Call list_children exactly once.\n"
        "2. Call send_message with to_node_id='user' and content equal to the tool result.\n"
        "3. Respond with one short sentence."
    )
    chat_prompt = "User asked for children. Use list_children then send_message to user."

    actor = event_store = workspace_service = db = src_dir_id = None
    try:
        actor, event_store, workspace_service, db, src_dir_id = await _setup_directory_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-directory-list-children"
        outbox = Outbox(
            actor_id=src_dir_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=src_dir_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=src_dir_id,
                content="List your children.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=100)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            item["event_type"] == "remora_tool_result"
            and item["payload"].get("tool_name") == "list_children"
            and not item["payload"].get("is_error")
            and "Children" in str(item["payload"].get("output_preview", ""))
            for item in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_directory_agent_summarize_tree(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "You manage a directory. For each chat turn:\n"
        "1. Call summarize_tree exactly once with max_depth=2.\n"
        "2. Call send_message with to_node_id='user' and content equal to the tool result.\n"
        "3. Respond with one short sentence."
    )
    chat_prompt = "User asked for tree summary. Use summarize_tree(max_depth=2)."

    actor = event_store = workspace_service = db = src_dir_id = None
    try:
        actor, event_store, workspace_service, db, src_dir_id = await _setup_directory_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-directory-summarize-tree"
        outbox = Outbox(
            actor_id=src_dir_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=src_dir_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=src_dir_id,
                content="Summarize your directory tree.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=100)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            item["event_type"] == "remora_tool_result"
            and item["payload"].get("tool_name") == "summarize_tree"
            and not item["payload"].get("is_error")
            and "Directory tree" in str(item["payload"].get("output_preview", ""))
            and "models" in str(item["payload"].get("output_preview", ""))
            for item in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_directory_agent_get_parent(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "You manage a directory. For each chat turn:\n"
        "1. Call get_parent exactly once.\n"
        "2. Call send_message with to_node_id='user' and content equal to the tool result.\n"
        "3. Respond with one short sentence."
    )
    chat_prompt = "User asked for parent. Use get_parent then send_message."

    actor = event_store = workspace_service = db = src_dir_id = None
    try:
        actor, event_store, workspace_service, db, src_dir_id = await _setup_directory_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-directory-get-parent"
        outbox = Outbox(
            actor_id=src_dir_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=src_dir_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=src_dir_id,
                content="What is your parent directory?",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=100)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            item["event_type"] == "remora_tool_result"
            and item["payload"].get("tool_name") == "get_parent"
            and not item["payload"].get("is_error")
            and "Parent:" in str(item["payload"].get("output_preview", ""))
            for item in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_directory_agent_broadcast_children(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "You manage a directory. For each chat turn:\n"
        "1. Call broadcast_children exactly once with message='ping'.\n"
        "2. Respond with one short sentence."
    )
    chat_prompt = "User asked for child broadcast. Use broadcast_children with message ping."

    actor = event_store = workspace_service = db = src_dir_id = None
    try:
        actor, event_store, workspace_service, db, src_dir_id = await _setup_directory_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-directory-broadcast-children"
        outbox = Outbox(
            actor_id=src_dir_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=src_dir_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=src_dir_id,
                content="Broadcast ping to your children.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=160)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)

        child_messages = [
            entry
            for entry in by_corr
            if entry["event_type"] == "agent_message" and entry["payload"].get("to_agent") != "user"
        ]
        assert len(child_messages) >= 2
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
