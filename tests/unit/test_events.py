from __future__ import annotations

import time

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    CursorFocusEvent,
    CustomEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    NodeChangedEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    RemoraToolCallEvent,
    RemoraToolResultEvent,
    RewriteAcceptedEvent,
    RewriteProposalEvent,
    RewriteRejectedEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    TurnDigestedEvent,
)
from remora.core.events.subscriptions import SubscriptionPattern


def test_agent_text_response_event_removed() -> None:
    import remora.core.events.types as event_types

    assert not hasattr(event_types, "AgentTextResponse")


def test_event_base_auto_type() -> None:
    event = AgentStartEvent(agent_id="a1")
    assert event.event_type == "agent_start"


def test_event_timestamp() -> None:
    before = time.time()
    event = AgentErrorEvent(agent_id="a1", error="boom")
    after = time.time()
    assert before <= event.timestamp <= after


def test_event_serialization() -> None:
    event = AgentMessageEvent(from_agent="a", to_agent="b", content="hello")
    dumped = event.model_dump()
    assert dumped["event_type"] == "agent_message"
    assert dumped["from_agent"] == "a"
    assert dumped["to_agent"] == "b"
    assert dumped["content"] == "hello"


def test_event_to_envelope_shape() -> None:
    event = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="hello",
        correlation_id="corr-1",
        tags=("chat",),
    )
    envelope = event.to_envelope()
    assert envelope["event_type"] == "agent_message"
    assert envelope["correlation_id"] == "corr-1"
    assert envelope["tags"] == ["chat"]
    assert envelope["payload"] == {
        "from_agent": "a",
        "to_agent": "b",
        "content": "hello",
    }


def test_custom_event_to_envelope_flattens_payload() -> None:
    event = CustomEvent(payload={"foo": "bar"}, tags=("custom",))
    envelope = event.to_envelope()
    assert envelope["event_type"] == "custom"
    assert envelope["tags"] == ["custom"]
    assert envelope["payload"] == {"foo": "bar"}


def test_subscription_pattern_matches_tags() -> None:
    event = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="hello",
        tags=("scaffold", "review"),
    )
    assert SubscriptionPattern(tags=["scaffold"]).matches(event)
    assert SubscriptionPattern(tags=["review"]).matches(event)
    assert not SubscriptionPattern(tags=["missing"]).matches(event)


def test_all_event_types_instantiate() -> None:
    events = [
        AgentStartEvent(agent_id="a", node_name="node"),
        AgentCompleteEvent(agent_id="a", result_summary="ok"),
        AgentErrorEvent(agent_id="a", error="err"),
        AgentMessageEvent(from_agent="a", to_agent="b", content="msg"),
        AgentMessageEvent(from_agent="user", to_agent="a", content="hello"),
        NodeDiscoveredEvent(
            node_id="src/app.py::f",
            node_type="function",
            file_path="src/app.py",
            name="f",
        ),
        NodeRemovedEvent(
            node_id="src/app.py::f",
            node_type="function",
            file_path="src/app.py",
            name="f",
        ),
        NodeChangedEvent(node_id="src/app.py::f", old_hash="old", new_hash="new"),
        ContentChangedEvent(
            path="src/app.py",
            change_type="modified",
            agent_id="a",
            old_hash="old",
            new_hash="new",
        ),
        HumanInputRequestEvent(
            agent_id="a",
            request_id="req-1",
            question="Proceed?",
            options=("yes", "no"),
        ),
        HumanInputResponseEvent(
            agent_id="a",
            request_id="req-1",
            response="yes",
        ),
        RewriteProposalEvent(
            agent_id="a",
            proposal_id="proposal-1",
            files=("source/src/app.py",),
            reason="Improve readability",
        ),
        RewriteAcceptedEvent(
            agent_id="a",
            proposal_id="proposal-1",
        ),
        RewriteRejectedEvent(
            agent_id="a",
            proposal_id="proposal-2",
            feedback="Please simplify",
        ),
        ModelRequestEvent(agent_id="a", model="mock", tool_count=2, turn=1),
        ModelResponseEvent(
            agent_id="a",
            response_preview="ok",
            duration_ms=42,
            tool_calls_count=1,
            turn=1,
        ),
        RemoraToolCallEvent(
            agent_id="a",
            tool_name="send_message",
            arguments_summary="{'to_node_id': 'user'}",
            turn=1,
        ),
        RemoraToolResultEvent(
            agent_id="a",
            tool_name="send_message",
            is_error=False,
            duration_ms=3,
            output_preview="sent",
            turn=1,
        ),
        TurnCompleteEvent(agent_id="a", turn=1, tool_calls_count=1, errors_count=0),
        TurnDigestedEvent(agent_id="a", digest_summary="digest"),
        ToolResultEvent(agent_id="a", tool_name="rewrite_self", result_summary="done"),
        CursorFocusEvent(file_path="src/app.py", line=3, character=0, node_id="src/app.py::a"),
    ]
    assert all(event.event_type for event in events)


def test_agent_complete_event_preserves_full_response() -> None:
    long_text = "x" * 500
    event = AgentCompleteEvent(
        agent_id="test",
        result_summary=long_text[:200],
        full_response=long_text,
    )
    assert len(event.result_summary) == 200
    assert len(event.full_response) == 500


def test_agent_complete_event_user_message_field() -> None:
    event = AgentCompleteEvent(
        agent_id="agent-a",
        result_summary="test",
        full_response="full test response",
        user_message="What does this function do?",
    )
    assert event.user_message == "What does this function do?"


def test_agent_complete_event_user_message_defaults_empty() -> None:
    event = AgentCompleteEvent(agent_id="agent-a")
    assert event.user_message == ""


def test_agent_complete_event_user_message_in_envelope() -> None:
    event = AgentCompleteEvent(
        agent_id="agent-a",
        user_message="hello",
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["user_message"] == "hello"


def test_turn_digested_event_defaults() -> None:
    event = TurnDigestedEvent(agent_id="agent-a")
    assert event.event_type == "turn_digested"
    assert event.digest_summary == ""
    assert event.tags == ()
    assert event.has_reflection is False
    assert event.has_links is False


def test_turn_digested_event_full() -> None:
    event = TurnDigestedEvent(
        agent_id="agent-a",
        digest_summary="Discussed validation",
        tags=("bug", "edge_case"),
        has_reflection=True,
        has_links=True,
    )
    assert event.agent_id == "agent-a"
    assert event.digest_summary == "Discussed validation"
    assert event.tags == ("bug", "edge_case")


def test_turn_digested_event_envelope() -> None:
    event = TurnDigestedEvent(agent_id="agent-a", digest_summary="test")
    envelope = event.to_envelope()
    assert envelope["event_type"] == "turn_digested"
    assert envelope["payload"]["agent_id"] == "agent-a"
    assert envelope["payload"]["digest_summary"] == "test"


def test_turn_digested_event_summary_method() -> None:
    """Verify summary() method returns digest_summary value."""
    event = TurnDigestedEvent(agent_id="agent-a", digest_summary="reflection completed")
    assert event.summary() == "reflection completed"
    assert event.summary() == event.digest_summary


def test_remora_tool_result_event_structured_error_fields() -> None:
    event = RemoraToolResultEvent(
        agent_id="agent-a",
        tool_name="review_diff",
        is_error=True,
        error_class="ToolError",
        error_reason="node not found",
        output_preview="Tool failed",
        turn=2,
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["is_error"] is True
    assert envelope["payload"]["error_class"] == "ToolError"
    assert envelope["payload"]["error_reason"] == "node not found"


def test_agent_error_event_structured_fields() -> None:
    event = AgentErrorEvent(
        agent_id="agent-a",
        error="Tool 'review_diff' failed: node not found",
        error_class="ToolError",
        error_reason="node not found",
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["error_class"] == "ToolError"
    assert envelope["payload"]["error_reason"] == "node not found"


def test_turn_complete_event_error_summary() -> None:
    event = TurnCompleteEvent(
        agent_id="agent-a",
        turn=3,
        tool_calls_count=2,
        errors_count=1,
        error_summary="ToolError",
    )
    envelope = event.to_envelope()
    assert envelope["payload"]["errors_count"] == 1
    assert envelope["payload"]["error_summary"] == "ToolError"
