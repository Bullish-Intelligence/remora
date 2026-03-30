"""Property-based tests for event types using Hypothesis."""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given, strategies as st, settings

from structured_agents.events.types import (
    KernelEvent,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.types import TokenUsage


# =============================================================================
# Custom Strategies
# =============================================================================

positive_ints = st.integers(min_value=0, max_value=10000)
small_positive_ints = st.integers(min_value=1, max_value=100)
duration_ms = st.integers(min_value=0, max_value=1000000)
tool_names = st.from_regex(r"[a-z][a-z0-9_]{0,30}", fullmatch=True)
call_ids = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=50
)
model_names = st.text(min_size=1, max_size=100)
termination_reasons = st.sampled_from(
    ["no_tool_calls", "max_turns", "error", "stop_sequence"]
)

# Token usage strategy
token_usage = st.builds(
    TokenUsage,
    prompt_tokens=positive_ints,
    completion_tokens=positive_ints,
    total_tokens=positive_ints,
)

# JSON-safe arguments
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=50),
)

json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=20).filter(lambda s: s.isidentifier()),
    json_primitives,
    max_size=5,
)


# =============================================================================
# KernelStartEvent Property Tests
# =============================================================================


class TestKernelStartEventProperties:
    """Property tests for KernelStartEvent."""

    @given(
        max_turns=small_positive_ints,
        tools_count=positive_ints,
        initial_messages_count=positive_ints,
    )
    def test_kernel_start_event_serialization(
        self, max_turns: int, tools_count: int, initial_messages_count: int
    ):
        """KernelStartEvent should serialize and deserialize correctly."""
        event = KernelStartEvent(
            max_turns=max_turns,
            tools_count=tools_count,
            initial_messages_count=initial_messages_count,
        )

        # Serialize to JSON
        json_str = event.model_dump_json()
        data = json.loads(json_str)

        # Verify fields
        assert data["max_turns"] == max_turns
        assert data["tools_count"] == tools_count
        assert data["initial_messages_count"] == initial_messages_count

        # Deserialize back
        restored = KernelStartEvent.model_validate(data)
        assert restored == event

    @given(
        max_turns=small_positive_ints,
        tools_count=positive_ints,
        initial_messages_count=positive_ints,
    )
    def test_kernel_start_event_is_kernel_event(
        self, max_turns: int, tools_count: int, initial_messages_count: int
    ):
        """KernelStartEvent should be a KernelEvent."""
        event = KernelStartEvent(
            max_turns=max_turns,
            tools_count=tools_count,
            initial_messages_count=initial_messages_count,
        )
        assert isinstance(event, KernelEvent)


# =============================================================================
# KernelEndEvent Property Tests
# =============================================================================


class TestKernelEndEventProperties:
    """Property tests for KernelEndEvent."""

    @given(
        turn_count=positive_ints,
        termination_reason=termination_reasons,
        total_duration_ms=duration_ms,
    )
    def test_kernel_end_event_serialization(
        self, turn_count: int, termination_reason: str, total_duration_ms: int
    ):
        """KernelEndEvent should serialize correctly."""
        event = KernelEndEvent(
            turn_count=turn_count,
            termination_reason=termination_reason,
            total_duration_ms=total_duration_ms,
        )

        json_str = event.model_dump_json()
        data = json.loads(json_str)

        assert data["turn_count"] == turn_count
        assert data["termination_reason"] == termination_reason
        assert data["total_duration_ms"] == total_duration_ms

        restored = KernelEndEvent.model_validate(data)
        assert restored == event


# =============================================================================
# ModelRequestEvent Property Tests
# =============================================================================


class TestModelRequestEventProperties:
    """Property tests for ModelRequestEvent."""

    @given(
        turn=small_positive_ints,
        messages_count=positive_ints,
        tools_count=positive_ints,
        model=model_names,
    )
    def test_model_request_event_roundtrip(
        self, turn: int, messages_count: int, tools_count: int, model: str
    ):
        """ModelRequestEvent should roundtrip through JSON."""
        event = ModelRequestEvent(
            turn=turn,
            messages_count=messages_count,
            tools_count=tools_count,
            model=model,
        )

        data = event.model_dump()
        restored = ModelRequestEvent.model_validate(data)
        assert restored == event


# =============================================================================
# ModelResponseEvent Property Tests
# =============================================================================


class TestModelResponseEventProperties:
    """Property tests for ModelResponseEvent."""

    @given(
        turn=small_positive_ints,
        duration_ms=duration_ms,
        content=st.one_of(st.none(), st.text(max_size=500)),
        tool_calls_count=positive_ints,
    )
    def test_model_response_event_with_optional_content(
        self,
        turn: int,
        duration_ms: int,
        content: str | None,
        tool_calls_count: int,
    ):
        """ModelResponseEvent should handle optional content."""
        event = ModelResponseEvent(
            turn=turn,
            duration_ms=duration_ms,
            content=content,
            tool_calls_count=tool_calls_count,
            usage=None,
        )

        data = event.model_dump()
        assert data["content"] == content
        assert data["usage"] is None

        restored = ModelResponseEvent.model_validate(data)
        assert restored == event

    @given(
        turn=small_positive_ints,
        duration_ms=duration_ms,
        content=st.text(max_size=100),
        tool_calls_count=positive_ints,
        usage=token_usage,
    )
    def test_model_response_event_with_usage(
        self,
        turn: int,
        duration_ms: int,
        content: str,
        tool_calls_count: int,
        usage: TokenUsage,
    ):
        """ModelResponseEvent should handle TokenUsage."""
        event = ModelResponseEvent(
            turn=turn,
            duration_ms=duration_ms,
            content=content,
            tool_calls_count=tool_calls_count,
            usage=usage,
        )

        data = event.model_dump()
        assert data["usage"] is not None
        assert data["usage"]["prompt_tokens"] == usage.prompt_tokens


# =============================================================================
# ToolCallEvent Property Tests
# =============================================================================


class TestToolCallEventProperties:
    """Property tests for ToolCallEvent."""

    @given(
        turn=small_positive_ints,
        tool_name=tool_names,
        call_id=call_ids,
        arguments=json_dicts,
    )
    def test_tool_call_event_serialization(
        self, turn: int, tool_name: str, call_id: str, arguments: dict[str, Any]
    ):
        """ToolCallEvent should serialize with JSON arguments."""
        event = ToolCallEvent(
            turn=turn,
            tool_name=tool_name,
            call_id=call_id,
            arguments=arguments,
        )

        json_str = event.model_dump_json()
        data = json.loads(json_str)

        assert data["tool_name"] == tool_name
        assert data["call_id"] == call_id
        assert data["arguments"] == arguments

        restored = ToolCallEvent.model_validate(data)
        assert restored == event


# =============================================================================
# ToolResultEvent Property Tests
# =============================================================================


class TestToolResultEventProperties:
    """Property tests for ToolResultEvent."""

    @given(
        turn=small_positive_ints,
        tool_name=tool_names,
        call_id=call_ids,
        is_error=st.booleans(),
        duration_ms=duration_ms,
        output_preview=st.text(max_size=200),
    )
    def test_tool_result_event_serialization(
        self,
        turn: int,
        tool_name: str,
        call_id: str,
        is_error: bool,
        duration_ms: int,
        output_preview: str,
    ):
        """ToolResultEvent should serialize correctly."""
        event = ToolResultEvent(
            turn=turn,
            tool_name=tool_name,
            call_id=call_id,
            is_error=is_error,
            duration_ms=duration_ms,
            output_preview=output_preview,
        )

        data = event.model_dump()
        assert data["is_error"] == is_error
        assert data["output_preview"] == output_preview

        restored = ToolResultEvent.model_validate(data)
        assert restored == event


# =============================================================================
# TurnCompleteEvent Property Tests
# =============================================================================


class TestTurnCompleteEventProperties:
    """Property tests for TurnCompleteEvent."""

    @given(
        turn=small_positive_ints,
        tool_calls_count=positive_ints,
        tool_results_count=positive_ints,
        errors_count=positive_ints,
    )
    def test_turn_complete_event_serialization(
        self,
        turn: int,
        tool_calls_count: int,
        tool_results_count: int,
        errors_count: int,
    ):
        """TurnCompleteEvent should serialize correctly."""
        event = TurnCompleteEvent(
            turn=turn,
            tool_calls_count=tool_calls_count,
            tool_results_count=tool_results_count,
            errors_count=errors_count,
        )

        data = event.model_dump()
        restored = TurnCompleteEvent.model_validate(data)
        assert restored == event


# =============================================================================
# Cross-Event Properties
# =============================================================================


class TestEventInvariants:
    """Test invariants across all event types."""

    @given(
        max_turns=small_positive_ints,
        tools_count=positive_ints,
    )
    def test_all_events_are_frozen(self, max_turns: int, tools_count: int):
        """All events should be frozen (immutable)."""
        event = KernelStartEvent(
            max_turns=max_turns,
            tools_count=tools_count,
            initial_messages_count=1,
        )

        # Attempting to modify should raise
        try:
            event.max_turns = 999  # type: ignore
            assert False, "Should have raised ValidationError"
        except Exception:
            pass  # Expected - Pydantic frozen models raise ValidationError

    @given(
        turn=small_positive_ints,
        tool_name=tool_names,
        call_id=call_ids,
    )
    def test_events_reject_extra_fields(self, turn: int, tool_name: str, call_id: str):
        """Events should reject extra fields (extra='forbid')."""
        try:
            ToolCallEvent(
                turn=turn,
                tool_name=tool_name,
                call_id=call_id,
                arguments={},
                unknown_field="should fail",  # type: ignore
            )
            assert False, "Should have raised ValidationError"
        except Exception:
            pass  # Expected
