from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from structured_agents import Message
from tests.factories import make_node

from remora.core.agents.actor import Actor, Outbox, Trigger
from remora.core.events import (
    ContentChangedEvent,
    EventBus,
    EventStore,
    RemoraToolResultEvent,
    SubscriptionRegistry,
    TriggerDispatcher,
    TurnCompleteEvent,
)
from remora.core.model.config import BehaviorConfig, Config, InfraConfig, RuntimeConfig
from remora.core.storage.db import open_database
from remora.core.storage.graph import NodeStore
from remora.core.storage.transaction import TransactionContext
from remora.core.storage.workspace import CairnWorkspaceService

_USER_TEMPLATE = (
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
async def event_error_env(tmp_path: Path):
    db = await open_database(tmp_path / "event-error-fields.db")
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
        infra=InfraConfig(workspace_root=".remora-event-error-fields"),
        runtime=RuntimeConfig(trigger_cooldown_ms=0, max_trigger_depth=5),
        behavior=BehaviorConfig(
            prompt_templates={"user": _USER_TEMPLATE},
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


def _make_actor(env: dict, node_id: str) -> Actor:
    return Actor(
        node_id=node_id,
        event_store=env["event_store"],
        node_store=env["node_store"],
        workspace_service=env["workspace_service"],
        config=env["config"],
        semaphore=env["semaphore"],
    )


def test_remora_tool_result_error_fields() -> None:
    event = RemoraToolResultEvent(
        agent_id="agent-a",
        tool_name="review_diff",
        is_error=True,
        error_class="ToolError",
        error_reason="node not found",
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["error_class"] == "ToolError"
    assert envelope["payload"]["error_reason"] == "node not found"


def test_turn_complete_error_summary_field() -> None:
    event = TurnCompleteEvent(
        agent_id="agent-a",
        turn=2,
        tool_calls_count=1,
        errors_count=1,
        error_summary="ToolError",
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["errors_count"] == 1
    assert envelope["payload"]["error_summary"] == "ToolError"


@pytest.mark.asyncio
async def test_content_changed_turn_preserves_correlation_id(event_error_env, monkeypatch) -> None:
    env = event_error_env
    node = make_node("src/app.py::correlation")
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

    correlation_id = "test-123"
    trigger_event = ContentChangedEvent(path=node.file_path, correlation_id=correlation_id)
    outbox = Outbox(
        actor_id=node.node_id,
        event_store=env["event_store"],
        correlation_id=correlation_id,
    )
    trigger = Trigger(node_id=node.node_id, correlation_id=correlation_id, event=trigger_event)
    actor = _make_actor(env, node.node_id)
    await actor._execute_turn(trigger, outbox)

    events = await env["event_store"].get_events(limit=50, correlation_id=correlation_id)
    assert events
    assert all(event["correlation_id"] == correlation_id for event in events)
    event_types = {event["event_type"] for event in events}
    assert "agent_start" in event_types
    assert "agent_complete" in event_types
