from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import aiosqlite
import pytest
import yaml
from tests.factories import make_node, write_file

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
from remora.core.services.broker import HumanInputBroker
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


def _write_system_project(tmp_path: Path) -> None:
    write_file(
        tmp_path / "src" / "app.py",
        "def alpha() -> int:\n    return 1\n\n\ndef beta() -> int:\n    return 2\n",
    )
    write_file(tmp_path / "src" / "worker.py", "def gamma() -> int:\n    return 3\n")


def _write_system_bundles(
    root: Path,
    model_name: str,
    system_prompt: str,
    chat_prompt: str,
) -> None:
    shutil.copytree(DEFAULTS_BUNDLES / "system", root / "system")
    bundle_path = root / "system" / "bundle.yaml"
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    data["model"] = model_name
    data["system_prompt"] = system_prompt
    data["max_turns"] = 6
    prompts = data.get("prompts") or {}
    prompts["chat"] = chat_prompt
    data["prompts"] = prompts
    bundle_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


async def _setup_system_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
    system_prompt: str,
    chat_prompt: str,
    broker: HumanInputBroker | None = None,
    search_service=None,
) -> tuple[Actor, EventStore, CairnWorkspaceService, aiosqlite.Connection, NodeStore, str]:
    _write_system_project(tmp_path)
    bundles_root = tmp_path / "bundles"
    _write_system_bundles(
        bundles_root,
        model_name,
        system_prompt,
        chat_prompt,
    )

    db = await open_database(tmp_path / "llm-system-tools.db")
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
                "function": "system",
                "class": "system",
                "method": "system",
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
    node = next((candidate for candidate in nodes if candidate.name == "alpha"), None)
    assert node is not None

    actor = Actor(
        node_id=node.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
        search_service=search_service,
        broker=broker,
    )
    return actor, event_store, workspace_service, db, node_store, node.node_id


def _events_for_correlation(events: list[dict], correlation_id: str) -> list[dict]:
    return [entry for entry in events if entry.get("correlation_id") == correlation_id]


def _tool_result_for_correlation(by_corr: list[dict], tool_name: str) -> list[dict]:
    return [
        entry
        for entry in by_corr
        if entry["event_type"] == "remora_tool_result"
        and entry["payload"].get("tool_name") == tool_name
    ]


def _assert_turn_success_and_tool(
    by_corr: list[dict],
    tool_name: str,
    *,
    output_contains: str | None = None,
) -> None:
    assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
    assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
    tool_results = _tool_result_for_correlation(by_corr, tool_name)
    assert tool_results
    assert not any(entry["payload"].get("is_error") for entry in tool_results)
    if output_contains is not None:
        assert any(
            output_contains in str(entry["payload"].get("output_preview", ""))
            for entry in tool_results
        )


async def _wait_for_event(
    event_store: EventStore,
    correlation_id: str,
    event_type: str,
    *,
    timeout_s: float = 20.0,
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        events = await event_store.get_events(limit=200)
        for entry in events:
            if (
                entry.get("correlation_id") == correlation_id
                and entry.get("event_type") == event_type
            ):
                return entry
        await asyncio.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {event_type} on correlation {correlation_id}")


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_broadcast(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call broadcast exactly once with pattern='*' and content='ping-all'. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use broadcast with pattern * and content ping-all."

    actor = event_store = workspace_service = db = _node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            _node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-broadcast"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Broadcast ping-all to everyone.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=140)
        by_corr = _events_for_correlation(events, correlation_id)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "broadcast"
            and "Broadcast sent to" in str(entry["payload"].get("output_preview", ""))
            for entry in by_corr
        )
        sent_messages = [entry for entry in by_corr if entry["event_type"] == "agent_message"]
        assert len(sent_messages) >= 2
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_query_agents(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call query_agents exactly once with no arguments. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use query_agents with no arguments."

    actor = event_store = workspace_service = db = _node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            _node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-query-agents"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Query all agents.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=120)
        by_corr = _events_for_correlation(events, correlation_id)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "query_agents"
            and "node_id" in str(entry["payload"].get("output_preview", ""))
            for entry in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_send_message(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call send_message exactly once with "
        "to_node_id='{node_id}' and content='self-ping'. Then respond with one sentence."
    )
    chat_prompt = "Use send_message now."

    actor = event_store = workspace_service = db = _node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            _node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-send-message"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call send_message to '{node_id}' with content 'self-ping'.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=180)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(
            by_corr,
            "send_message",
            output_contains="Message sent to",
        )
        assert any(
            entry["event_type"] == "agent_message"
            and entry["payload"].get("from_agent") == node_id
            and entry["payload"].get("to_agent") == node_id
            and entry["payload"].get("content") == "self-ping"
            for entry in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_kv_set_get_roundtrip(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call kv_set exactly once with key='session/flag' and value='ready'. "
        "Then call kv_get exactly once with key='session/flag'. Then respond with one sentence."
    )
    chat_prompt = "Use kv_set and kv_get now."

    actor = event_store = workspace_service = db = _node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            _node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-kv-roundtrip"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call kv_set and kv_get for session/flag.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=220)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(
            by_corr,
            "kv_set",
            output_contains="Stored value for session/flag",
        )
        _assert_turn_success_and_tool(by_corr, "kv_get")
        kv_get_results = _tool_result_for_correlation(by_corr, "kv_get")
        assert any(
            "ready" in str(item["payload"].get("output_preview", ""))
            for item in kv_get_results
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        stored = await workspace.kv_get("session/flag")
        assert stored == "ready"
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_reflect(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call reflect exactly once with history_limit=5, "
        "then respond with one sentence."
    )
    chat_prompt = "Use reflect now."

    actor = event_store = workspace_service = db = _node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            _node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-reflect"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Record a reflection note.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=120)
        by_corr = _events_for_correlation(events, correlation_id)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "reflect"
            and "Reflection recorded" in str(entry["payload"].get("output_preview", ""))
            for entry in by_corr
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        reflection = await workspace.read("notes/reflection.md")
        assert "Reviewed recent activity." in reflection
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_subscribe_unsubscribe(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "Follow the user request exactly and call either subscribe or unsubscribe as requested. "
        "Do not call unrelated tools."
    )
    chat_prompt = "Follow user subscription commands exactly."

    actor = event_store = workspace_service = db = _node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            _node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        first_corr = "corr-system-subscribe"
        first_outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=first_corr)
        first_trigger = Trigger(
            node_id=node_id,
            correlation_id=first_corr,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call subscribe with event_types='node_changed'.",
                correlation_id=first_corr,
            ),
        )
        await actor._execute_turn(first_trigger, first_outbox)

        events = await event_store.get_events(limit=160)
        first_events = _events_for_correlation(events, first_corr)
        assert any(entry["event_type"] == "agent_complete" for entry in first_events)
        assert not any(entry["event_type"] == "agent_error" for entry in first_events)

        subscribe_result = next(
            (
                entry
                for entry in first_events
                if entry["event_type"] == "remora_tool_result"
                and entry["payload"].get("tool_name") == "subscribe"
            ),
            None,
        )
        assert subscribe_result is not None
        assert not subscribe_result["payload"].get("is_error")
        cursor = await db.execute(
            "SELECT id FROM subscriptions WHERE agent_id = ? ORDER BY id DESC LIMIT 1",
            (node_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        subscription_id = int(row[0])

        second_corr = "corr-system-unsubscribe"
        second_outbox = Outbox(
            actor_id=node_id,
            event_store=event_store,
            correlation_id=second_corr,
        )
        second_trigger = Trigger(
            node_id=node_id,
            correlation_id=second_corr,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call unsubscribe with subscription_id={subscription_id}.",
                correlation_id=second_corr,
            ),
        )
        await actor._execute_turn(second_trigger, second_outbox)

        events = await event_store.get_events(limit=200)
        second_events = _events_for_correlation(events, second_corr)
        assert any(entry["event_type"] == "agent_complete" for entry in second_events)
        assert not any(entry["event_type"] == "agent_error" for entry in second_events)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "unsubscribe"
            and "Unsubscribed" in str(entry["payload"].get("output_preview", ""))
            for entry in second_events
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_categorize_writes_meta_file(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call categorize exactly once with "
        "node_id='{node_id}'. Then respond with one sentence."
    )
    chat_prompt = "Use categorize now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-categorize"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call categorize with node_id='{node_id}'.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=160)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(
            by_corr,
            "categorize",
            output_contains="Categorization updated",
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        category_file = await workspace.read("meta/categories.md")
        assert "# Categories" in category_file
        assert "Primary:" in category_file
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_find_links_writes_meta_file(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call find_links exactly once with "
        "node_id='{node_id}'. Then respond with one sentence."
    )
    chat_prompt = "Use find_links now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        target_node_id = "src/lib.py::delta"
        await node_store.upsert_node(
            make_node(
                target_node_id,
                file_path="src/lib.py",
                text="def delta() -> int:\n    return 4\n",
            )
        )
        await node_store.add_edge(node_id, target_node_id, "calls")

        correlation_id = "corr-system-find-links"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call find_links with node_id='{node_id}'.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=180)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(
            by_corr,
            "find_links",
            output_contains="Recorded",
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        links_file = await workspace.read("meta/links.md")
        assert "# Links" in links_file
        assert "calls:" in links_file
        assert target_node_id in links_file
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_summarize_writes_summary_file(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call summarize exactly once with "
        "node_id='{node_id}' and history_limit=10. Then respond with one sentence."
    )
    chat_prompt = "Use summarize now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-summarize"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call summarize with node_id='{node_id}' and history_limit=10.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=160)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(by_corr, "summarize", output_contains="Summary updated")

        workspace = await workspace_service.get_agent_workspace(node_id)
        summary_file = await workspace.read("notes/summary.md")
        assert "# Recent Activity Summary" in summary_file
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_companion_summarize_records_chat_index(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call companion_summarize exactly once with "
        "summary='Tracked integration coverage progress' and tags='coverage,tests'. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use companion_summarize now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-companion-summarize"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call companion_summarize now.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=180)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(
            by_corr,
            "companion_summarize",
            output_contains="Recorded summary with tags",
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        chat_index = await workspace.kv_get("companion/chat_index")
        assert isinstance(chat_index, list) and chat_index
        latest = chat_index[-1]
        assert latest.get("summary") == "Tracked integration coverage progress"
        assert "coverage" in latest.get("tags", [])
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_companion_reflect_records_reflection(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call companion_reflect exactly once with "
        "insight='Need broader real-world integration checks'. Then respond with one sentence."
    )
    chat_prompt = "Use companion_reflect now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-companion-reflect"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call companion_reflect now.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=180)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(
            by_corr,
            "companion_reflect",
            output_contains="Recorded reflection",
        )

        workspace = await workspace_service.get_agent_workspace(node_id)
        reflections = await workspace.kv_get("companion/reflections")
        assert isinstance(reflections, list) and reflections
        assert reflections[-1].get("insight") == "Need broader real-world integration checks"
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_companion_link_records_link(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    target_node_id = "src/worker.py::gamma"
    system_prompt = (
        "For each chat turn, call companion_link exactly once with "
        f"target_node_id='{target_node_id}'. Then respond with one sentence."
    )
    chat_prompt = "Use companion_link now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-companion-link"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content=f"Call companion_link with target_node_id='{target_node_id}'.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=180)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(by_corr, "companion_link", output_contains="Linked to")

        workspace = await workspace_service.get_agent_workspace(node_id)
        links = await workspace.kv_get("companion/links")
        assert isinstance(links, list) and links
        assert any(
            item.get("target") == target_node_id and item.get("relationship") == "related"
            for item in links
            if isinstance(item, dict)
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_semantic_search_executes_tool(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call semantic_search exactly once with "
        "query='alpha function behavior', collection='code', top_k=3. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use semantic_search now."

    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
        )

        correlation_id = "corr-system-semantic-search"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call semantic_search now.",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=180)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(by_corr, "semantic_search")
        tool_results = _tool_result_for_correlation(by_corr, "semantic_search")
        assert any(
            str(entry["payload"].get("output_preview", "")).strip()
            for entry in tool_results
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_system_ask_human_roundtrip(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    system_prompt = (
        "For each chat turn, call ask_human exactly once with "
        "question='Proceed with remediation?' and options='yes,no'. "
        "Then respond with one sentence."
    )
    chat_prompt = "Use ask_human now."

    broker = HumanInputBroker()
    actor = event_store = workspace_service = db = node_store = node_id = None
    try:
        (
            actor,
            event_store,
            workspace_service,
            db,
            node_store,
            node_id,
        ) = await _setup_system_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            system_prompt=system_prompt,
            chat_prompt=chat_prompt,
            broker=broker,
        )

        correlation_id = "corr-system-ask-human"
        outbox = Outbox(actor_id=node_id, event_store=event_store, correlation_id=correlation_id)
        trigger = Trigger(
            node_id=node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node_id,
                content="Call ask_human now.",
                correlation_id=correlation_id,
            ),
        )
        execute_task = asyncio.create_task(actor._execute_turn(trigger, outbox))
        request_event = await _wait_for_event(
            event_store,
            correlation_id,
            "human_input_request",
            timeout_s=30.0,
        )
        request_payload = request_event["payload"]
        request_id = str(request_payload.get("request_id", "")).strip()
        assert request_id
        assert request_payload.get("question") == "Proceed with remediation?"
        assert request_payload.get("options") == ["yes", "no"]
        assert broker.resolve(request_id, "yes")
        await asyncio.wait_for(execute_task, timeout=30.0)

        events = await event_store.get_events(limit=220)
        by_corr = _events_for_correlation(events, correlation_id)
        _assert_turn_success_and_tool(by_corr, "ask_human")
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
