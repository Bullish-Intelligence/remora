"""Tests for actor model primitives."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from structured_agents import Message
from structured_agents.events import (
    ModelRequestEvent as SAModelRequestEvent,
)
from structured_agents.events import (
    ModelResponseEvent as SAModelResponseEvent,
)
from structured_agents.events import (
    ToolCallEvent as SAToolCallEvent,
)
from structured_agents.events import (
    ToolResultEvent as SAToolResultEvent,
)
from structured_agents.events import (
    TurnCompleteEvent as SATurnCompleteEvent,
)
from tests.doubles import RecordingOutbox
from tests.factories import make_node

from remora.core.agents.actor import (
    Actor,
    Outbox,
    PromptBuilder,
    Trigger,
    TriggerPolicy,
)
from remora.core.events import (
    AgentCompleteEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    EventBus,
    EventStore,
    SubscriptionRegistry,
    TriggerDispatcher,
)
from remora.core.model.config import (
    BehaviorConfig,
    BundleConfig,
    Config,
    InfraConfig,
    RuntimeConfig,
)
from remora.core.model.types import EventType, NodeStatus
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService

_TEST_USER_TEMPLATE = (
    "# Node: {node_full_name}\n"
    "Type: {node_type} | File: {file_path}\n"
    "Role: {role}\n\n"
    "## Source Code\n"
    "```\n"
    "{source}\n"
    "```\n\n"
    "## Trigger\n"
    "Event: {event_type}\n"
    "{event_content}\n"
)


async def _empty_tools(*_args, **_kwargs):  # noqa: ANN001
    return []


@pytest_asyncio.fixture
async def outbox_env(tmp_path: Path):
    db = await open_database(tmp_path / "outbox.db")
    event_bus = EventBus()
    dispatcher = TriggerDispatcher()
    tx = TransactionContext(db, event_bus, dispatcher)
    subscriptions = SubscriptionRegistry(db, tx=tx)
    dispatcher.subscriptions = subscriptions
    event_store = EventStore(db=db, event_bus=event_bus, dispatcher=dispatcher, tx=tx)
    await event_store.create_tables()
    outbox = Outbox(actor_id="agent-a", event_store=event_store, correlation_id="corr-1")
    yield outbox, event_store, db
    await db.close()


@pytest.mark.asyncio
async def test_outbox_emit_persists_event(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event_id = await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    assert event_id == 1
    events = await event_store.get_events(limit=1)
    assert events[0]["event_type"] == "agent_start"


@pytest.mark.asyncio
async def test_outbox_tags_correlation_id(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event = AgentStartEvent(agent_id="agent-a")
    assert event.correlation_id is None
    await outbox.emit(event)
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_outbox_preserves_existing_correlation_id(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    event = AgentStartEvent(agent_id="agent-a", correlation_id="original")
    await outbox.emit(event)
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "original"


@pytest.mark.asyncio
async def test_outbox_increments_sequence(outbox_env) -> None:
    outbox, _event_store, _db = outbox_env
    assert outbox.sequence == 0
    await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    assert outbox.sequence == 1
    await outbox.emit(AgentCompleteEvent(agent_id="agent-a"))
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_outbox_correlation_id_setter(outbox_env) -> None:
    outbox, event_store, _db = outbox_env
    outbox.correlation_id = "new-corr"
    await outbox.emit(AgentStartEvent(agent_id="agent-a"))
    events = await event_store.get_events(limit=1)
    assert events[0]["correlation_id"] == "new-corr"


@pytest.mark.asyncio
async def test_recording_outbox_captures_events() -> None:
    outbox = RecordingOutbox(actor_id="test-agent")
    outbox.correlation_id = "corr-1"
    await outbox.emit(AgentStartEvent(agent_id="test-agent"))
    await outbox.emit(AgentCompleteEvent(agent_id="test-agent"))
    assert len(outbox.events) == 2
    assert outbox.events[0].event_type == "agent_start"
    assert outbox.events[1].event_type == "agent_complete"
    assert all(event.correlation_id == "corr-1" for event in outbox.events)
    assert outbox.sequence == 2


@pytest.mark.asyncio
async def test_recording_outbox_no_persistence() -> None:
    outbox = RecordingOutbox()
    event_id = await outbox.emit(AgentStartEvent(agent_id="x"))
    assert event_id == 1
    assert len(outbox.events) == 1


@pytest_asyncio.fixture
async def actor_env(tmp_path: Path):
    db = await open_database(tmp_path / "actor.db")
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
        infra=InfraConfig(workspace_root=".remora-actor-test"),
        runtime=RuntimeConfig(trigger_cooldown_ms=1000, max_trigger_depth=2),
        behavior=BehaviorConfig(
            prompt_templates={"user": _TEST_USER_TEMPLATE},
            model_default="mock",
            max_turns=1,
        ),
    )
    workspace_service = CairnWorkspaceService(config, tmp_path)
    await workspace_service.initialize()
    semaphore = asyncio.Semaphore(4)

    yield {
        "db": db,
        "node_store": node_store,
        "event_store": event_store,
        "config": config,
        "workspace_service": workspace_service,
        "semaphore": semaphore,
    }

    await workspace_service.close()
    await db.close()


def _make_actor(env: dict, node_id: str = "src/app.py::a") -> Actor:
    return Actor(
        node_id=node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=env["semaphore"],
    )


@pytest.mark.asyncio
async def test_actor_start_stop(actor_env) -> None:
    actor = _make_actor(actor_env)
    actor.start()
    assert actor.is_running
    await actor.stop()
    assert not actor.is_running


@pytest.mark.asyncio
async def test_actor_cooldown(actor_env) -> None:
    policy = TriggerPolicy(actor_env["config"])
    assert policy.should_trigger("c1")
    assert not policy.should_trigger("c1")


@pytest.mark.asyncio
async def test_actor_depth_limit(actor_env) -> None:
    policy = TriggerPolicy(actor_env["config"])
    assert policy.should_trigger("c1")
    policy.last_trigger_ms = 0.0
    assert policy.should_trigger("c1")
    policy.last_trigger_ms = 0.0
    assert not policy.should_trigger("c1")


@pytest.mark.asyncio
async def test_actor_depth_cleanup_removes_stale_entries(actor_env, monkeypatch) -> None:
    policy = TriggerPolicy(actor_env["config"])
    now_seconds = 1_700_000.0
    now_ms = now_seconds * 1000.0
    policy.depths["stale-corr"] = 1
    policy.depth_timestamps["stale-corr"] = now_ms - (5 * 60 * 1000) - 1
    policy.depths["fresh-corr"] = 1
    policy.depth_timestamps["fresh-corr"] = now_ms
    policy.trigger_checks = 99
    monkeypatch.setattr("remora.core.agents.actor.time.time", lambda: now_seconds)

    assert policy.should_trigger("new-corr")
    assert "stale-corr" not in policy.depths
    assert "stale-corr" not in policy.depth_timestamps
    assert "fresh-corr" in policy.depths


def test_trigger_policy_release_clears_depth_timestamp(actor_env) -> None:
    policy = TriggerPolicy(actor_env["config"])
    assert policy.should_trigger("corr-reset")

    policy.release_depth("corr-reset")

    assert "corr-reset" not in policy.depths
    assert "corr-reset" not in policy.depth_timestamps


def test_trigger_policy_limits_reactive_turns_per_correlation() -> None:
    config = Config(
        infra=InfraConfig(workspace_root=".remora-trigger-policy"),
        runtime=RuntimeConfig(
            trigger_cooldown_ms=0,
            max_trigger_depth=50,
        ),
        behavior=BehaviorConfig(prompt_templates={"user": _TEST_USER_TEMPLATE}),
    )
    policy = TriggerPolicy(config)

    assert policy.should_trigger("corr-loop")
    policy.release_depth("corr-loop")

    assert policy.should_trigger("corr-loop")
    policy.release_depth("corr-loop")

    assert policy.should_trigger("corr-loop")
    policy.release_depth("corr-loop")

    assert not policy.should_trigger("corr-loop")


@pytest.mark.asyncio
async def test_actor_processes_inbox_message(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::a")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user", to_agent=node.node_id, content="hello", correlation_id="corr-1"
    )

    outbox = Outbox(actor_id=node.node_id, event_store=env["event_store"], correlation_id="corr-1")
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-1", event=event)
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=10)
    event_types = [event["event_type"] for event in events]
    assert "agent_start" in event_types
    assert "agent_complete" in event_types

    updated = await env["node_store"].get_node(node.node_id)
    assert updated is not None
    assert updated.status == "idle"


@pytest.mark.asyncio
async def test_actor_emits_primary_tag_on_normal_completion(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::tag-primary")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-primary",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-primary",
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=20)
    complete = next(event for event in events if event["event_type"] == "agent_complete")
    assert complete["tags"] == ["primary"]


@pytest.mark.asyncio
async def test_actor_emits_reflection_tag_on_self_completion_trigger(
    actor_env, monkeypatch
) -> None:
    env = actor_env
    node = make_node("src/app.py::tag-reflection")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="reflect"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger_event = AgentCompleteEvent(
        agent_id=node.node_id,
        result_summary="primary turn",
        full_response="primary response",
        tags=("primary",),
    )
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-reflection",
        event=trigger_event,
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-reflection",
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=20)
    complete = next(event for event in events if event["event_type"] == "agent_complete")
    assert complete["tags"] == ["reflection"]


@pytest.mark.asyncio
async def test_actor_emits_turn_digested_after_reflection_turn(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::turn-digested")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")
    await ws.kv_set("companion/chat_index", [{"summary": "digest summary", "tags": ["review"]}])
    await ws.kv_set("companion/reflections", [{"insight": "captured reflection"}])
    await ws.kv_set("companion/links", [{"target": "src/app.py::callee", "relationship": "calls"}])

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="reflect"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-turn-digested",
        event=AgentCompleteEvent(
            agent_id=node.node_id,
            result_summary="primary turn",
            full_response="primary response",
            tags=("primary",),
        ),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-turn-digested",
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=30)
    digested = next(event for event in events if event["event_type"] == EventType.TURN_DIGESTED)
    payload = digested["payload"]
    assert payload["agent_id"] == node.node_id
    assert payload["digest_summary"] == "digest summary"
    assert payload["has_reflection"] is True
    assert payload["has_links"] is True
    assert digested["tags"] == ["review"]
    assert digested["correlation_id"] == "corr-turn-digested"


@pytest.mark.asyncio
async def test_actor_does_not_emit_turn_digested_for_primary_turn(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::turn-digested-primary")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-turn-digested-primary",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-turn-digested-primary",
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=20)
    event_types = [event["event_type"] for event in events]
    assert EventType.TURN_DIGESTED not in event_types


@pytest.mark.asyncio
async def test_actor_emits_user_message_on_completion(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::user-message")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-user-message",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello world"),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-user-message",
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=20)
    complete = next(event for event in events if event["event_type"] == "agent_complete")
    assert "hello world" in complete["payload"]["user_message"]


def test_prompt_builder_reflection_override() -> None:
    config = Config()
    prompt_builder = PromptBuilder(config)
    bundle_config = BundleConfig.model_validate(
        {
            "system_prompt": "Normal prompt",
            "model": "big-model",
            "max_turns": 8,
            "self_reflect": {
                "enabled": True,
                "model": "Qwen/Qwen3-1.7B",
                "max_turns": 2,
                "prompt": "Reflect on this turn.",
            },
        }
    )
    trigger = AgentCompleteEvent(agent_id="agent-a", tags=("primary",))
    turn_config = prompt_builder.build_turn_config(bundle_config, trigger)
    assert turn_config.system_prompt == "Reflect on this turn."
    assert turn_config.model == "Qwen/Qwen3-1.7B"
    assert turn_config.max_turns == 2


def test_prompt_builder_normal_turn_unaffected_by_self_reflect() -> None:
    config = Config()
    prompt_builder = PromptBuilder(config)
    bundle_config = BundleConfig.model_validate(
        {
            "system_prompt": "Normal prompt",
            "model": "big-model",
            "max_turns": 8,
            "self_reflect": {
                "enabled": True,
                "model": "Qwen/Qwen3-1.7B",
            },
        }
    )
    trigger = ContentChangedEvent(path="src/foo.py")
    turn_config = prompt_builder.build_turn_config(bundle_config, trigger)
    assert "Normal prompt" in turn_config.system_prompt
    assert turn_config.model == "big-model"
    assert turn_config.max_turns == 8


def test_prompt_builder_reflection_tag_must_be_primary() -> None:
    config = Config()
    prompt_builder = PromptBuilder(config)
    bundle_config = BundleConfig.model_validate(
        {
            "system_prompt": "Normal prompt",
            "model": "big-model",
            "self_reflect": {"enabled": True, "model": "cheap-model"},
        }
    )
    trigger = AgentCompleteEvent(agent_id="agent-a", tags=("reflection",))
    turn_config = prompt_builder.build_turn_config(bundle_config, trigger)
    assert "Normal prompt" in turn_config.system_prompt
    assert turn_config.model == "big-model"


def test_prompt_builder_build_user_prompt_interpolates_default_template() -> None:
    config = Config(
        behavior=BehaviorConfig(
            prompt_templates={
                "user": (
                    "Node={node_full_name}|Type={node_type}|File={file_path}|Role={role}|"
                    "Event={event_type}|Content={event_content}|Mode={turn_mode}|"
                    "Companion={companion_context}|Source={source}"
                )
            },
            model_default="mock",
            max_turns=1,
        ),
    )
    prompt_builder = PromptBuilder(config)
    node = make_node("src/app.py::alpha", role="code-agent", text="def alpha():\n    return 1\n")
    trigger = AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello")

    prompt = prompt_builder.build_user_prompt(
        node,
        trigger,
        companion_context="memory-block",
    )

    assert "Node=alpha" in prompt
    assert "Type=function" in prompt
    assert "File=src/app.py" in prompt
    assert "Role=code-agent" in prompt
    assert "Event=agent_message" in prompt
    assert "Content=hello" in prompt
    assert "Mode=chat" in prompt
    assert "Companion=memory-block" in prompt
    assert "Source=def alpha():" in prompt


def test_prompt_builder_build_user_prompt_bundle_template_override() -> None:
    config = Config(
        behavior=BehaviorConfig(
            prompt_templates={"user": "default:{node_name}"},
            model_default="mock",
            max_turns=1,
        ),
    )
    prompt_builder = PromptBuilder(config)
    node = make_node("src/app.py::alpha", role="code-agent", text="def alpha():\n    return 1\n")
    trigger = ContentChangedEvent(path="src/app.py")
    bundle_config = BundleConfig(
        system_prompt="system",
        model="mock",
        max_turns=1,
        prompt_templates={"user": "bundle:{node_name}:{event_type}"},
    )

    prompt = prompt_builder.build_user_prompt(node, trigger, bundle_config=bundle_config)
    assert prompt == "bundle:alpha:content_changed"


def test_prompt_builder_interpolate_no_double_replacement() -> None:
    template = "Name: {name}, Source: {source}"
    variables = {
        "name": "my_func",
        "source": "def my_func():\n    return '{name}'",
    }

    result = PromptBuilder._interpolate(template, variables)
    assert "Name: my_func" in result
    assert "return '{name}'" in result


def test_prompt_builder_interpolate_unknown_vars_preserved() -> None:
    result = PromptBuilder._interpolate("{known} {unknown}", {"known": "hello"})
    assert result == "hello {unknown}"


@pytest.mark.asyncio
async def test_build_companion_context_empty(actor_env) -> None:
    from remora.core.agents.prompt import PromptBuilder

    workspace = await actor_env["workspace_service"].get_agent_workspace(
        "src/app.py::companion-empty"
    )
    companion_data = await workspace.get_companion_data()
    result = PromptBuilder.format_companion_context(companion_data)
    assert result == ""


@pytest.mark.asyncio
async def test_build_companion_context_with_data(actor_env) -> None:
    from remora.core.agents.prompt import PromptBuilder

    workspace = await actor_env["workspace_service"].get_agent_workspace(
        "src/app.py::companion-data"
    )
    await workspace.kv_set(
        "companion/reflections",
        [{"insight": "Regex does not handle Unicode domains", "timestamp": 1.0}],
    )
    await workspace.kv_set(
        "companion/chat_index",
        [{"summary": "Discussed email validation", "tags": ["bug"], "timestamp": 1.0}],
    )
    await workspace.kv_set(
        "companion/links",
        [{"target": "test_validate", "relationship": "tested_by", "timestamp": 1.0}],
    )

    companion_data = await workspace.get_companion_data()
    result = PromptBuilder.format_companion_context(companion_data)
    assert "Companion Memory" in result
    assert "Unicode domains" in result
    assert "email validation" in result
    assert "test_validate" in result


@pytest.mark.asyncio
async def test_companion_context_injected_for_primary_turn(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::companion-primary")
    await env["node_store"].upsert_node(node)
    workspace = await env["workspace_service"].get_agent_workspace(node.node_id)
    await workspace.write("_bundle/bundle.yaml", "system_prompt: base\nmodel: mock\nmax_turns: 1\n")
    await workspace.kv_set(
        "companion/reflections",
        [{"insight": "Watch edge-case around unicode input"}],
    )

    captured_system_prompts: list[str] = []

    class MockKernel:
        async def run(self, messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            captured_system_prompts.append(messages[0].content)
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-companion-primary",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-companion-primary",
    )
    await actor._execute_turn(trigger, outbox)

    assert captured_system_prompts
    assert "## Companion Memory" in captured_system_prompts[0]
    assert "unicode input" in captured_system_prompts[0]


@pytest.mark.asyncio
async def test_companion_context_not_injected_for_reflection_turn(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::companion-reflection")
    await env["node_store"].upsert_node(node)
    workspace = await env["workspace_service"].get_agent_workspace(node.node_id)
    await workspace.write(
        "_bundle/bundle.yaml",
        (
            "system_prompt: base\n"
            "model: mock\n"
            "max_turns: 1\n"
            "self_reflect:\n"
            "  enabled: true\n"
            "  prompt: reflection-only\n"
        ),
    )
    await workspace.kv_set(
        "companion/reflections",
        [{"insight": "This should not be appended on reflection turns"}],
    )

    captured_system_prompts: list[str] = []

    class MockKernel:
        async def run(self, messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            captured_system_prompts.append(messages[0].content)
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-companion-reflection",
        event=AgentCompleteEvent(
            agent_id=node.node_id,
            result_summary="primary done",
            full_response="primary done",
            tags=("primary",),
        ),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-companion-reflection",
    )
    await actor._execute_turn(trigger, outbox)

    assert captured_system_prompts
    assert captured_system_prompts[0] == "reflection-only"
    assert "Companion Memory" not in captured_system_prompts[0]


@pytest.mark.asyncio
async def test_actor_missing_node(actor_env) -> None:
    actor = _make_actor(actor_env, "missing-node")
    outbox = Outbox(actor_id="missing-node", event_store=actor_env["event_store"])
    trigger = Trigger(node_id="missing-node", correlation_id="c1")
    await actor._execute_turn(trigger, outbox)
    events = await actor_env["event_store"].get_events(limit=5)
    assert not any(event["event_type"] == "agent_start" for event in events)


@pytest.mark.asyncio
async def test_read_bundle_config_expands_model_from_env_default(actor_env, monkeypatch) -> None:
    monkeypatch.delenv("REMORA_MODEL", raising=False)
    node_id = "src/config.py::f"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write(
        "_bundle/bundle.yaml",
        'model: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"\n',
    )

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.model == "Qwen/Qwen3-4B-Instruct-2507-FP8"


@pytest.mark.asyncio
async def test_read_bundle_config_allows_env_override_for_placeholder(
    actor_env,
    monkeypatch,
) -> None:
    monkeypatch.setenv("REMORA_MODEL", "my-org/custom-model")
    node_id = "src/config.py::g"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", 'model: "${REMORA_MODEL:-Qwen/Qwen3-4B}"\n')

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.model == "my-org/custom-model"


@pytest.mark.asyncio
async def test_read_bundle_config_literal_model_overrides_env(actor_env, monkeypatch) -> None:
    monkeypatch.setenv("REMORA_MODEL", "my-org/custom-model")
    node_id = "src/config.py::h"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", "model: pinned/model\n")

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.model == "pinned/model"


@pytest.mark.asyncio
async def test_read_bundle_config_malformed_yaml_returns_empty(actor_env) -> None:
    node_id = "src/config.py::bad"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", "system_prompt: [oops\n")

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config == BundleConfig()


@pytest.mark.asyncio
async def test_read_bundle_config_parses_self_reflect(actor_env) -> None:
    node_id = "src/config.py::self-reflect"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write(
        "_bundle/bundle.yaml",
        (
            'system_prompt: "You are a code agent."\n'
            "self_reflect:\n"
            "  enabled: true\n"
            '  model: "Qwen/Qwen3-1.7B"\n'
            "  max_turns: 2\n"
            '  prompt: "Reflect on your last turn."\n'
        ),
    )

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.self_reflect is not None
    assert bundle_config.self_reflect.enabled is True
    assert bundle_config.self_reflect.model == "Qwen/Qwen3-1.7B"
    assert bundle_config.self_reflect.max_turns == 2
    assert bundle_config.self_reflect.prompt == "Reflect on your last turn."


@pytest.mark.asyncio
async def test_read_bundle_config_ignores_disabled_self_reflect(actor_env) -> None:
    node_id = "src/config.py::self-reflect-disabled"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write(
        "_bundle/bundle.yaml",
        ('system_prompt: "You are a code agent."\nself_reflect:\n  enabled: false\n'),
    )

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.self_reflect is None


@pytest.mark.asyncio
async def test_read_bundle_config_passes_through_externals_version(actor_env) -> None:
    """read_bundle_config returns the version as-is; enforcement is in the turn executor."""
    node_id = "src/app.py::externals-version-pass"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", "externals_version: 999\n")

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.externals_version == 999


@pytest.mark.asyncio
async def test_read_bundle_config_defaults_externals_version_to_none(actor_env) -> None:
    """Without explicit externals_version, bundle config defaults to None."""
    node_id = "src/app.py::externals-version-none"
    workspace = await actor_env["workspace_service"].get_agent_workspace(node_id)
    await workspace.write("_bundle/bundle.yaml", "model: mock\n")

    bundle_config = await actor_env["workspace_service"].read_bundle_config(node_id)
    assert bundle_config.externals_version is None


@pytest.mark.asyncio
async def test_actor_reload_reads_updated_bundle_config_each_turn(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::dynamic-config")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: first\nmodel: model-a\nmax_turns: 1\n")

    seen_models: list[str] = []

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    def capture_kernel(**kwargs):  # noqa: ANN003, ANN202
        seen_models.append(kwargs["model_name"])
        return MockKernel()

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", capture_kernel)
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    outbox = Outbox(actor_id=node.node_id, event_store=env["event_store"], correlation_id="corr-a")
    trigger_a = Trigger(
        node_id=node.node_id,
        correlation_id="corr-a",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello"),
    )
    await actor._execute_turn(trigger_a, outbox)

    await ws.write("_bundle/bundle.yaml", "system_prompt: second\nmodel: model-b\nmax_turns: 1\n")
    trigger_b = Trigger(
        node_id=node.node_id,
        correlation_id="corr-b",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="hello again"),
    )
    await actor._execute_turn(trigger_b, outbox)

    assert seen_models == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_actor_logs_model_request_and_response(actor_env, monkeypatch, caplog) -> None:
    env = actor_env
    node = make_node("src/app.py::logged")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-log",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-log",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-log", event=event)

    with caplog.at_level(logging.DEBUG, logger="remora.core.agents.turn"):
        await actor._execute_turn(trigger, outbox)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Model request node=src/app.py::logged corr=corr-log" in message for message in messages
    )
    assert any(
        "Agent turn complete node=src/app.py::logged corr=corr-log response=ok" in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_turn_logs_include_correlation_id(actor_env, monkeypatch, caplog) -> None:
    env = actor_env
    node = make_node("src/app.py::log-context")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-turn-context",
        event=AgentMessageEvent(
            from_agent="user",
            to_agent=node.node_id,
            content="hello",
            correlation_id="corr-turn-context",
        ),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-turn-context",
    )

    with caplog.at_level(logging.DEBUG, logger="remora.core.agents.turn"):
        await actor._execute_turn(trigger, outbox)

    assert any(
        getattr(record, "correlation_id", None) == "corr-turn-context" for record in caplog.records
    )


@pytest.mark.asyncio
async def test_actor_logs_full_response_not_truncated(actor_env, monkeypatch, caplog) -> None:
    env = actor_env
    node = make_node("src/app.py::logged-long")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    long_response = "r" * 1400 + "TAIL"

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content=long_response))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-long",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-long",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-long", event=event)

    with caplog.at_level(logging.DEBUG, logger="remora.core.agents.turn"):
        await actor._execute_turn(trigger, outbox)

    messages = [record.getMessage() for record in caplog.records]
    completion = next(
        message
        for message in messages
        if "Agent turn complete node=src/app.py::logged-long corr=corr-long response=" in message
    )
    assert "TAIL" in completion
    assert "..." not in completion


@pytest.mark.asyncio
async def test_actor_logging_preserves_newlines(actor_env, monkeypatch, caplog) -> None:
    env = actor_env
    node = make_node("src/app.py::logged-newlines")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write(
        "_bundle/bundle.yaml",
        'system_prompt: "line1\\nline2"\nmodel: mock\nmax_turns: 1\n',
    )

    class MockKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: MockKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello\nworld",
        correlation_id="corr-log-nl",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-log-nl",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-log-nl", event=event)

    with caplog.at_level(logging.DEBUG, logger="remora.core.agents.turn"):
        await actor._execute_turn(trigger, outbox)

    request = next(
        message
        for message in (record.getMessage() for record in caplog.records)
        if "Model request node=src/app.py::logged-newlines corr=corr-log-nl" in message
    )
    assert "line1\nline2" in request
    assert "hello\nworld" in request
    assert "line1\\nline2" not in request
    assert "hello\\nworld" not in request


@pytest.mark.asyncio
async def test_actor_execute_turn_emits_error_event_on_kernel_failure(
    actor_env,
    monkeypatch,
) -> None:
    env = actor_env
    node = make_node("src/app.py::kernel-fail")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    def fail_create_kernel(**_kwargs):  # noqa: ANN003, ANN202
        raise ConnectionError("connection refused")

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", fail_create_kernel)
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-fail",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-fail",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-fail", event=event)
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=10)
    event_types = [event["event_type"] for event in events]
    assert EventType.AGENT_START in event_types
    assert EventType.AGENT_ERROR in event_types
    assert EventType.AGENT_COMPLETE not in event_types

    error_event = next(event for event in events if event["event_type"] == EventType.AGENT_ERROR)
    assert "connection refused" in error_event["payload"]["error"]
    assert error_event["payload"]["error_class"] == "ModelError"
    assert "connection refused" in error_event["payload"]["error_reason"]

    updated_node = await env["node_store"].get_node(node.node_id)
    assert updated_node is not None
    assert updated_node.status == NodeStatus.ERROR


@pytest.mark.asyncio
async def test_actor_execute_turn_retries_kernel_once(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::kernel-retry")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    attempts = 0

    class RetryKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            nonlocal attempts
            del max_turns
            attempts += 1
            if attempts == 1:
                raise ConnectionError("transient")
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: RetryKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)
    monkeypatch.setattr("remora.core.agents.turn.asyncio.sleep", _no_sleep)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-retry",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-retry",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-retry", event=event)
    await actor._execute_turn(trigger, outbox)

    assert attempts == 2
    events = await env["event_store"].get_events(limit=10)
    event_types = [event["event_type"] for event in events]
    assert EventType.AGENT_COMPLETE in event_types
    assert EventType.AGENT_ERROR not in event_types


@pytest.mark.asyncio
async def test_actor_execute_turn_honors_configured_retry_count(actor_env, monkeypatch) -> None:
    env = actor_env
    env["config"] = Config(
        infra=InfraConfig(workspace_root=".remora-actor-test"),
        runtime=RuntimeConfig(
            trigger_cooldown_ms=1000,
            max_trigger_depth=2,
            max_model_retries=0,
        ),
        behavior=BehaviorConfig(
            prompt_templates={"user": _TEST_USER_TEMPLATE},
            model_default="mock",
            max_turns=1,
        ),
    )

    node = make_node("src/app.py::kernel-no-retry")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    attempts = 0

    class FailKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            nonlocal attempts
            del max_turns
            attempts += 1
            raise ConnectionError("always-fails")

        async def close(self) -> None:
            return None

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", lambda **_kwargs: FailKernel())
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)
    monkeypatch.setattr("remora.core.agents.turn.asyncio.sleep", _no_sleep)

    actor = _make_actor(env, node.node_id)
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-no-retry",
        event=AgentMessageEvent(
            from_agent="user",
            to_agent=node.node_id,
            content="hello",
            correlation_id="corr-no-retry",
        ),
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-no-retry",
    )
    await actor._execute_turn(trigger, outbox)

    assert attempts == 1
    events = await env["event_store"].get_events(limit=10)
    event_types = [event["event_type"] for event in events]
    assert EventType.AGENT_ERROR in event_types


@pytest.mark.asyncio
async def test_actor_execute_turn_respects_shared_semaphore(actor_env, monkeypatch) -> None:
    env = actor_env
    node_a = make_node("src/app.py::sem-a")
    node_b = make_node("src/app.py::sem-b")
    await env["node_store"].upsert_node(node_a)
    await env["node_store"].upsert_node(node_b)

    ws_a = await env["workspace_service"].get_agent_workspace(node_a.node_id)
    ws_b = await env["workspace_service"].get_agent_workspace(node_b.node_id)
    await ws_a.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")
    await ws_b.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    gate = asyncio.Event()
    first_run_started = asyncio.Event()
    in_flight = 0
    max_in_flight = 0
    counter_lock = asyncio.Lock()

    class BlockingKernel:
        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            nonlocal in_flight, max_in_flight
            async with counter_lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            first_run_started.set()
            await gate.wait()
            async with counter_lock:
                in_flight -= 1
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "remora.core.agents.turn.create_kernel", lambda **_kwargs: BlockingKernel()
    )
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    shared_semaphore = asyncio.Semaphore(1)
    actor_a = Actor(
        node_id=node_a.node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=shared_semaphore,
    )
    actor_b = Actor(
        node_id=node_b.node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=shared_semaphore,
    )

    outbox_a = Outbox(
        actor_id=node_a.node_id,
        event_store=env["event_store"],
        correlation_id="corr-sem-a",
    )
    outbox_b = Outbox(
        actor_id=node_b.node_id,
        event_store=env["event_store"],
        correlation_id="corr-sem-b",
    )
    trigger_a = Trigger(
        node_id=node_a.node_id,
        correlation_id="corr-sem-a",
        event=AgentMessageEvent(from_agent="user", to_agent=node_a.node_id, content="go"),
    )
    trigger_b = Trigger(
        node_id=node_b.node_id,
        correlation_id="corr-sem-b",
        event=AgentMessageEvent(from_agent="user", to_agent=node_b.node_id, content="go"),
    )

    task_a = asyncio.create_task(actor_a._execute_turn(trigger_a, outbox_a))
    await asyncio.wait_for(first_run_started.wait(), timeout=1.0)
    task_b = asyncio.create_task(actor_b._execute_turn(trigger_b, outbox_b))
    await asyncio.sleep(0.05)
    assert not task_b.done()

    gate.set()
    await asyncio.gather(task_a, task_b)
    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_actor_emits_kernel_observability_events(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::observed")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class ObservedKernel:
        def __init__(self, observer):
            self._observer = observer

        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            await self._observer.emit(
                SAModelRequestEvent(turn=1, messages_count=2, tools_count=1, model="mock")
            )
            await self._observer.emit(
                SAModelResponseEvent(
                    turn=1,
                    duration_ms=12,
                    content="hello",
                    tool_calls_count=1,
                    usage=None,
                )
            )
            await self._observer.emit(
                SAToolCallEvent(
                    turn=1,
                    tool_name="send_message",
                    call_id="call-1",
                    arguments={"to_node_id": "user"},
                )
            )
            await self._observer.emit(
                SAToolResultEvent(
                    turn=1,
                    tool_name="send_message",
                    call_id="call-1",
                    is_error=False,
                    duration_ms=3,
                    output_preview="sent",
                )
            )
            await self._observer.emit(
                SATurnCompleteEvent(
                    turn=1,
                    tool_calls_count=1,
                    tool_results_count=1,
                    errors_count=0,
                )
            )
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    def capture_kernel(**kwargs):  # noqa: ANN003, ANN202
        return ObservedKernel(kwargs["observer"])

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", capture_kernel)
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-observe",
    )
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-observe",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="observe"),
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=30)
    event_types = [event["event_type"] for event in events]
    assert "model_request" in event_types
    assert "model_response" in event_types
    assert "remora_tool_call" in event_types
    assert "remora_tool_result" in event_types
    assert "turn_complete" in event_types


@pytest.mark.asyncio
async def test_actor_emits_structured_tool_error_observability_events(
    actor_env, monkeypatch
) -> None:
    env = actor_env
    node = make_node("src/app.py::observed-errors")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write("_bundle/bundle.yaml", "system_prompt: hi\nmodel: mock\nmax_turns: 1\n")

    class ObservedErrorKernel:
        def __init__(self, observer):
            self._observer = observer

        async def run(self, _messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            del max_turns
            await self._observer.emit(
                SAToolResultEvent(
                    turn=2,
                    tool_name="review_diff",
                    call_id="call-err-1",
                    is_error=True,
                    duration_ms=7,
                    output_preview=(
                        "Tool 'review_diff' failed: TypeError: "
                        "expected dict but received None"
                    ),
                )
            )
            await self._observer.emit(
                SATurnCompleteEvent(
                    turn=2,
                    tool_calls_count=1,
                    tool_results_count=1,
                    errors_count=1,
                )
            )
            return SimpleNamespace(final_message=Message(role="assistant", content="done"))

        async def close(self) -> None:
            return None

    def capture_kernel(**kwargs):  # noqa: ANN003, ANN202
        return ObservedErrorKernel(kwargs["observer"])

    monkeypatch.setattr("remora.core.agents.turn.create_kernel", capture_kernel)
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-observe-error",
    )
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-observe-error",
        event=AgentMessageEvent(from_agent="user", to_agent=node.node_id, content="observe"),
    )
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=40)
    tool_error = next(event for event in events if event["event_type"] == "remora_tool_result")
    assert tool_error["correlation_id"] == "corr-observe-error"
    assert tool_error["payload"]["is_error"] is True
    assert tool_error["payload"]["error_class"] == "TypeError"
    assert "expected dict but received None" in tool_error["payload"]["error_reason"]

    turn_complete = next(event for event in events if event["event_type"] == "turn_complete")
    assert turn_complete["correlation_id"] == "corr-observe-error"
    assert turn_complete["payload"]["errors_count"] == 1
    assert "TypeError" in turn_complete["payload"]["error_summary"]


@pytest.mark.asyncio
async def test_actor_chat_mode_injects_prompt(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::mode-chat")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write(
        "_bundle/bundle.yaml",
        (
            "system_prompt: base\n"
            "model: mock\n"
            "max_turns: 1\n"
            "prompts:\n"
            "  chat: CHAT_MODE\n"
            "  reactive: REACTIVE_MODE\n"
        ),
    )

    captured_system_prompt = ""

    class CapturingKernel:
        async def run(self, messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            nonlocal captured_system_prompt
            del max_turns
            captured_system_prompt = messages[0].content or ""
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "remora.core.agents.turn.create_kernel", lambda **_kwargs: CapturingKernel()
    )
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=node.node_id,
        content="hello",
        correlation_id="corr-mode-chat",
    )
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-mode-chat",
    )
    trigger = Trigger(node_id=node.node_id, correlation_id="corr-mode-chat", event=event)
    await actor._execute_turn(trigger, outbox)

    assert "CHAT_MODE" in captured_system_prompt
    assert "REACTIVE_MODE" not in captured_system_prompt


@pytest.mark.asyncio
async def test_actor_reactive_mode_injects_prompt(actor_env, monkeypatch) -> None:
    env = actor_env
    node = make_node("src/app.py::mode-reactive")
    await env["node_store"].upsert_node(node)
    ws = await env["workspace_service"].get_agent_workspace(node.node_id)
    await ws.write(
        "_bundle/bundle.yaml",
        (
            "system_prompt: base\n"
            "model: mock\n"
            "max_turns: 1\n"
            "prompts:\n"
            "  chat: CHAT_MODE\n"
            "  reactive: REACTIVE_MODE\n"
        ),
    )

    captured_system_prompt = ""

    class CapturingKernel:
        async def run(self, messages, _tools, max_turns=20):  # noqa: ANN001, ANN201
            nonlocal captured_system_prompt
            del max_turns
            captured_system_prompt = messages[0].content or ""
            return SimpleNamespace(final_message=Message(role="assistant", content="ok"))

        async def close(self) -> None:
            return None

    monkeypatch.setattr(
        "remora.core.agents.turn.create_kernel", lambda **_kwargs: CapturingKernel()
    )
    monkeypatch.setattr("remora.core.agents.turn.discover_tools", _empty_tools)

    actor = _make_actor(env, node.node_id)
    event = ContentChangedEvent(path=node.file_path, change_type="modified")
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id="corr-mode-reactive",
    )
    trigger = Trigger(
        node_id=node.node_id,
        correlation_id="corr-mode-reactive",
        event=event,
    )
    await actor._execute_turn(trigger, outbox)

    assert "REACTIVE_MODE" in captured_system_prompt
    assert "CHAT_MODE" not in captured_system_prompt
