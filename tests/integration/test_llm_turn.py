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
    ContentChangedEvent,
    EventBus,
    EventStore,
    NodeChangedEvent,
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


def _write_llm_test_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a tool-using test agent. You must call send_message exactly once,\n"
            "  then answer with one short sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 6\n"
        ),
    )
    write_file(
        code / "bundle.yaml",
        f"name: code-agent\nmodel: {model_name}\nmax_turns: 6\n",
    )
    write_file(
        system / "tools" / "send_message.pym",
        (
            "from grail import Input, external\n\n"
            'to_node_id: str = Input("to_node_id")\n'
            'content: str = Input("content")\n\n'
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> dict[str, object]: ...\n\n"
            "result = await send_message(to_node_id, content)\n"
            "if result.get(\"sent\"):\n"
            '    message = f"Message sent to {to_node_id}"\n'
            "else:\n"
            '    reason = result.get("reason", "unknown")\n'
            '    message = f"Message not sent to {to_node_id} ({reason})"\n'
            "message\n"
        ),
    )


def _write_kv_roundtrip_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a deterministic integration-test agent.\n"
            "  For user requests, call the requested tools in order.\n"
            "  Use send_message exactly once after kv_set and kv_get.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
    )
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 8\n")
    write_file(
        system / "tools" / "send_message.pym",
        (
            "from grail import Input, external\n\n"
            'to_node_id: str = Input("to_node_id")\n'
            'content: str = Input("content")\n\n'
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> dict[str, object]: ...\n\n"
            "result = await send_message(to_node_id, content)\n"
            "if result.get(\"sent\"):\n"
            '    message = f"Message sent to {to_node_id}"\n'
            "else:\n"
            '    reason = result.get("reason", "unknown")\n'
            '    message = f"Message not sent to {to_node_id} ({reason})"\n'
            "message\n"
        ),
    )
    write_file(
        system / "tools" / "kv_set.pym",
        (
            "from grail import Input, external\n\n"
            'key: str = Input("key")\n'
            'value: str = Input("value")\n\n'
            "@external\n"
            "async def kv_set(key: str, value: str) -> None: ...\n\n"
            "await kv_set(key, value)\n"
            'message = f"Stored value for {key}"\n'
            "message\n"
        ),
    )
    write_file(
        system / "tools" / "kv_get.pym",
        (
            "from grail import Input, external\n\n"
            'key: str = Input("key")\n\n'
            "@external\n"
            "async def kv_get(key: str) -> str | None: ...\n\n"
            "value = await kv_get(key)\n"
            'result = "" if value is None else str(value)\n'
            "result\n"
        ),
    )


def _write_reactive_mode_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (
            "name: system\n"
            "system_prompt: >-\n"
            "  You are a deterministic integration-test agent.\n"
            "  Mandatory protocol for every turn:\n"
            "  1) Read MODE_TOKEN from the active mode prompt.\n"
            "  2) Call send_message exactly once with to_node_id='src/app.py::alpha'\n"
            "     and content equal to MODE_TOKEN.\n"
            "  3) Then reply with one short sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
            "prompts:\n"
            "  chat: |\n"
            "    MODE_TOKEN=chat-ok\n"
            "  reactive: |\n"
            "    MODE_TOKEN=reactive-ok\n"
        ),
    )
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 8\n")
    write_file(
        system / "tools" / "send_message.pym",
        (
            "from grail import Input, external\n\n"
            'to_node_id: str = Input("to_node_id")\n'
            'content: str = Input("content")\n\n'
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> dict[str, object]: ...\n\n"
            "result = await send_message(to_node_id, content)\n"
            "if result.get(\"sent\"):\n"
            '    message = f"Message sent to {to_node_id}"\n'
            "else:\n"
            '    reason = result.get("reason", "unknown")\n'
            '    message = f"Message not sent to {to_node_id} ({reason})"\n'
            "message\n"
        ),
    )


def _write_virtual_agent_bundles(root: Path, model_name: str) -> None:
    system = root / "system"
    test_agent = root / "test-agent"
    code = root / "code-agent"
    (system / "tools").mkdir(parents=True, exist_ok=True)
    (test_agent / "tools").mkdir(parents=True, exist_ok=True)
    (code / "tools").mkdir(parents=True, exist_ok=True)

    write_file(
        system / "bundle.yaml",
        (f"name: system\nsystem_prompt: Base system\nmodel: {model_name}\nmax_turns: 8\n"),
    )
    write_file(code / "bundle.yaml", "name: code-agent\nmax_turns: 8\n")
    write_file(
        test_agent / "bundle.yaml",
        (
            "name: test-agent\n"
            "system_prompt: >-\n"
            "  You are a virtual test agent.\n"
            "  For every turn, call send_message exactly once with\n"
            "  to_node_id='test-agent' and content='virtual-reactive-ok',\n"
            "  then answer with one short sentence.\n"
            f"model: {model_name}\n"
            "max_turns: 8\n"
        ),
    )
    write_file(
        system / "tools" / "send_message.pym",
        (
            "from grail import Input, external\n\n"
            'to_node_id: str = Input("to_node_id")\n'
            'content: str = Input("content")\n\n'
            "@external\n"
            "async def send_message(to_node_id: str, content: str) -> dict[str, object]: ...\n\n"
            "result = await send_message(to_node_id, content)\n"
            "if result.get(\"sent\"):\n"
            '    message = f"Message sent to {to_node_id}"\n'
            "else:\n"
            '    reason = result.get("reason", "unknown")\n'
            '    message = f"Message not sent to {to_node_id} ({reason})"\n'
            "message\n"
        ),
    )


def _write_real_code_agent_bundles(root: Path, model_name: str) -> None:
    for bundle_name in ("system", "code-agent"):
        shutil.copytree(DEFAULTS_BUNDLES / bundle_name, root / bundle_name)

    system_bundle = root / "system" / "bundle.yaml"
    system_data = yaml.safe_load(system_bundle.read_text(encoding="utf-8"))
    system_data["model"] = model_name
    system_bundle.write_text(yaml.safe_dump(system_data, sort_keys=False), encoding="utf-8")

    code_bundle = root / "code-agent" / "bundle.yaml"
    code_data = yaml.safe_load(code_bundle.read_text(encoding="utf-8"))
    code_data["model"] = model_name
    code_data["system_prompt"] = (
        "You are a strict integration-test code agent. "
        "For each turn, follow the user instruction exactly and call only requested tools."
    )
    code_data["max_turns"] = 6
    code_data["self_reflect"] = {"enabled": False}
    prompts = code_data.get("prompts") or {}
    prompts["chat"] = "Follow user tool instructions exactly."
    code_data["prompts"] = prompts
    code_bundle.write_text(yaml.safe_dump(code_data, sort_keys=False), encoding="utf-8")


async def _setup_llm_runtime(
    tmp_path: Path,
    *,
    model_url: str,
    model_name: str,
    model_api_key: str,
    timeout_s: float,
    bundle_writer,
) -> tuple[Actor, object, EventStore, CairnWorkspaceService, aiosqlite.Connection, Path]:
    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    bundle_writer(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-turn.db")
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
    node = next(candidate for candidate in nodes if candidate.node_type != "directory")

    actor = Actor(
        node_id=node.node_id,
        event_store=event_store,
        node_store=node_store,
        workspace_service=workspace_service,
        config=config,
        semaphore=asyncio.Semaphore(1),
    )
    return actor, node, event_store, workspace_service, db, source_path


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_turn_invokes_tool_and_completes(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    _write_llm_test_bundles(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-turn.db")
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
            max_turns=6,
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

    try:
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
        node = next(candidate for candidate in nodes if candidate.node_type != "directory")

        actor = Actor(
            node_id=node.node_id,
            event_store=event_store,
            node_store=node_store,
            workspace_service=workspace_service,
            config=config,
            semaphore=asyncio.Semaphore(1),
        )
        correlation_id = "corr-llm-turn"
        event = AgentMessageEvent(
            from_agent="user",
            to_agent=node.node_id,
            content=(
                f"Use the send_message tool exactly once with to_node_id='{node.node_id}' and "
                "content='integration-ok'. Then give a one-line confirmation."
            ),
            correlation_id=correlation_id,
        )
        outbox = Outbox(
            actor_id=node.node_id, event_store=event_store, correlation_id=correlation_id
        )
        trigger = Trigger(node_id=node.node_id, correlation_id=correlation_id, event=event)
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=30)
        event_types = [entry["event_type"] for entry in events]
        assert "agent_start" in event_types
        assert "agent_complete" in event_types
        assert "agent_error" not in event_types

        message_events = [entry for entry in events if entry["event_type"] == "agent_message"]
        assert message_events, "expected at least one send_message tool emission"
        assert any(
            item["payload"].get("to_agent") == node.node_id
            and item["payload"].get("content") == "integration-ok"
            for item in message_events
        )
    finally:
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_turn_kv_roundtrip_and_message(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_kv_roundtrip_bundles,
        )
        correlation_id = "corr-llm-kv"
        outbox = Outbox(
            actor_id=node.node_id, event_store=event_store, correlation_id=correlation_id
        )
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content=(
                    "Call kv_set with key='state/integration' and value='v-integration', "
                    "then call kv_get for key='state/integration', then call send_message with "
                    f"to_node_id='{node.node_id}' and content='kv-ok:v-integration'."
                ),
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        workspace = await workspace_service.get_agent_workspace(node.node_id)
        assert await workspace.kv_get("state/integration") == "v-integration"

        events = await event_store.get_events(limit=40)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "agent_message"
            and entry["payload"].get("to_agent") == node.node_id
            and "v-integration" in str(entry["payload"].get("content", ""))
            for entry in by_corr
        )
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_turn_reload_uses_runtime_bundle_mutation(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_llm_test_bundles,
        )
        corr_a = "corr-reload-a"
        outbox_a = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=corr_a)
        trigger_a = Trigger(
            node_id=node.node_id,
            correlation_id=corr_a,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content="Briefly acknowledge this turn.",
                correlation_id=corr_a,
            ),
        )
        await actor._execute_turn(trigger_a, outbox_a)

        workspace = await workspace_service.get_agent_workspace(node.node_id)
        await workspace.write(
            "_bundle/bundle.yaml",
            (
                "name: system\n"
                "system_prompt: Runtime mutated config\n"
                "model: does/not-exist-in-vllm\n"
                "max_turns: 4\n"
            ),
        )

        corr_b = "corr-reload-b"
        outbox_b = Outbox(actor_id=node.node_id, event_store=event_store, correlation_id=corr_b)
        trigger_b = Trigger(
            node_id=node.node_id,
            correlation_id=corr_b,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content="This turn should use the mutated model config.",
                correlation_id=corr_b,
            ),
        )
        await actor._execute_turn(trigger_b, outbox_b)

        events = await event_store.get_events(limit=60)
        first_turn = [entry for entry in events if entry.get("correlation_id") == corr_a]
        second_turn = [entry for entry in events if entry.get("correlation_id") == corr_b]
        assert any(entry["event_type"] == "agent_complete" for entry in first_turn)
        assert not any(entry["event_type"] == "agent_error" for entry in first_turn)
        assert any(entry["event_type"] == "agent_error" for entry in second_turn)
        assert not any(entry["event_type"] == "agent_complete" for entry in second_turn)
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_code_agent_reflect_writes_to_workspace(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_real_code_agent_bundles,
        )
        correlation_id = "corr-code-agent-reflect"
        outbox = Outbox(
            actor_id=node.node_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content=f"Call reflect with node_id='{node.node_id}' and history_limit=5.",
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
            and entry["payload"].get("tool_name") == "reflect"
            and not entry["payload"].get("is_error")
            for entry in by_corr
        )

        workspace = await workspace_service.get_agent_workspace(node.node_id)
        reflection = await workspace.read("notes/reflection.md")
        assert "Reviewed recent activity." in reflection
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_code_agent_subscribe_to_events(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_real_code_agent_bundles,
        )
        correlation_id = "corr-code-agent-subscribe"
        outbox = Outbox(
            actor_id=node.node_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content="Call subscribe with event_types='node_changed'.",
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
            and entry["payload"].get("tool_name") == "subscribe"
            and not entry["payload"].get("is_error")
            for entry in by_corr
        )

        cursor = await db.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE agent_id = ?",
            (node.node_id,),
        )
        row = await cursor.fetchone()
        assert row is not None and int(row[0]) >= 1
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_code_agent_rewrite_self_proposes_changes(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_real_code_agent_bundles,
        )
        correlation_id = "corr-code-agent-rewrite-self"
        outbox = Outbox(
            actor_id=node.node_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content=(
                    "Call rewrite_self exactly once with "
                    "new_source='def alpha():\\n    return 42\\n' and "
                    "reason='integration rewrite self test'."
                ),
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=120)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "rewrite_self"
            and not entry["payload"].get("is_error")
            for entry in by_corr
        )
        proposal_events = [entry for entry in by_corr if entry["event_type"] == "rewrite_proposal"]
        assert proposal_events
        proposal_payload = proposal_events[0]["payload"]
        expected_workspace_path = f"source/{node.node_id.lstrip('/')}"
        assert expected_workspace_path in proposal_payload.get("files", [])

        workspace = await workspace_service.get_agent_workspace(node.node_id)
        rewritten = await workspace.read(expected_workspace_path)
        assert rewritten == "def alpha():\n    return 42\n"
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_code_agent_scaffold_emits_scaffold_request(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, _source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_real_code_agent_bundles,
        )
        correlation_id = "corr-code-agent-scaffold"
        outbox = Outbox(
            actor_id=node.node_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=AgentMessageEvent(
                from_agent="user",
                to_agent=node.node_id,
                content=(
                    "Call scaffold exactly once with "
                    "intent='Add tests for edge cases', element_type='function', "
                    f"agent_id='{node.node_id}'."
                ),
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=120)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "remora_tool_result"
            and entry["payload"].get("tool_name") == "scaffold"
            and not entry["payload"].get("is_error")
            for entry in by_corr
        )
        scaffold_events = [
            entry for entry in by_corr if entry["event_type"] == "ScaffoldRequestEvent"
        ]
        assert scaffold_events
        payload = scaffold_events[0]["payload"]
        assert payload["agent_id"] == node.node_id
        assert payload["intent"] == "Add tests for edge cases"
        assert payload["element_type"] == "function"
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_virtual_agent_reacts_to_node_changed(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    source_path = tmp_path / "src" / "app.py"
    write_file(source_path, "def alpha():\n    return 1\n")
    bundles_root = tmp_path / "bundles"
    _write_virtual_agent_bundles(bundles_root, model_name)

    db = await open_database(tmp_path / "llm-turn-virtual.db")
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

    try:
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

        virtual = await node_store.get_node("test-agent")
        assert virtual is not None
        actor = Actor(
            node_id=virtual.node_id,
            event_store=event_store,
            node_store=node_store,
            workspace_service=workspace_service,
            config=config,
            semaphore=asyncio.Semaphore(1),
        )
        correlation_id = "corr-virtual-reactive"
        trigger_event = NodeChangedEvent(
            node_id=str(source_path) + "::alpha",
            old_hash="old",
            new_hash="new",
            file_path="src/app.py",
            correlation_id=correlation_id,
        )
        outbox = Outbox(
            actor_id=virtual.node_id,
            event_store=event_store,
            correlation_id=correlation_id,
        )
        trigger = Trigger(
            node_id=virtual.node_id,
            correlation_id=correlation_id,
            event=trigger_event,
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=60)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_start" for entry in by_corr)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
        assert any(
            entry["event_type"] == "agent_message"
            and entry["payload"].get("to_agent") == "test-agent"
            and entry["payload"].get("content") == "virtual-reactive-ok"
            for entry in by_corr
        )
    finally:
        await workspace_service.close()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.skipif(_REAL_LLM_ENV_MISSING, reason=_REAL_LLM_SKIP_REASON)
async def test_real_llm_reactive_trigger_uses_reactive_mode_prompt(tmp_path: Path) -> None:
    model_url = os.environ["REMORA_TEST_MODEL_URL"]
    model_name = os.getenv("REMORA_TEST_MODEL_NAME", DEFAULT_TEST_MODEL_NAME)
    model_api_key = os.getenv("REMORA_TEST_MODEL_API_KEY", "EMPTY")
    timeout_s = float(os.getenv("REMORA_TEST_TIMEOUT_S", "90"))

    actor = node = event_store = workspace_service = db = None
    try:
        actor, node, event_store, workspace_service, db, source_path = await _setup_llm_runtime(
            tmp_path,
            model_url=model_url,
            model_name=model_name,
            model_api_key=model_api_key,
            timeout_s=timeout_s,
            bundle_writer=_write_reactive_mode_bundles,
        )
        correlation_id = "corr-reactive-mode"
        outbox = Outbox(
            actor_id=node.node_id, event_store=event_store, correlation_id=correlation_id
        )
        trigger = Trigger(
            node_id=node.node_id,
            correlation_id=correlation_id,
            event=ContentChangedEvent(
                path=str(source_path),
                change_type="modified",
                correlation_id=correlation_id,
            ),
        )
        await actor._execute_turn(trigger, outbox)

        events = await event_store.get_events(limit=50)
        by_corr = [entry for entry in events if entry.get("correlation_id") == correlation_id]
        assert any(entry["event_type"] == "agent_start" for entry in by_corr)
        assert any(entry["event_type"] == "agent_complete" for entry in by_corr)
        assert not any(entry["event_type"] == "agent_error" for entry in by_corr)
    finally:
        if workspace_service is not None:
            await workspace_service.close()
        if db is not None:
            await db.close()
