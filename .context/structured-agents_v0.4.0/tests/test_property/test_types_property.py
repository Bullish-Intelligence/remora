"""Property-based tests using Hypothesis for structured-agents types."""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given, strategies as st, assume, settings

from structured_agents.types import (
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
)


# =============================================================================
# Custom Strategies
# =============================================================================

# Strategy for valid role types
roles = st.sampled_from(["user", "assistant", "system", "tool"])

# Strategy for tool names (valid identifiers)
tool_names = st.from_regex(r"[a-z][a-z0-9_]{0,30}", fullmatch=True)

# Strategy for simple JSON-serializable dicts
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=100),
)

json_values = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
    ),
    max_leaves=10,
)

json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=20).filter(lambda s: s.isidentifier()),
    json_values,
    max_size=10,
)

# Strategy for tool call IDs
call_ids = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=1,
    max_size=50,
)


# =============================================================================
# Message Property Tests
# =============================================================================


class TestMessageProperties:
    """Property-based tests for Message type."""

    @given(role=roles, content=st.text(max_size=1000))
    def test_message_roundtrip_openai_format(self, role: str, content: str):
        """Message should preserve role and content through OpenAI format."""
        msg = Message(role=role, content=content)
        openai_fmt = msg.to_openai_format()

        assert openai_fmt["role"] == role
        assert openai_fmt["content"] == content

    @given(role=roles, content=st.text(max_size=500))
    def test_message_immutability(self, role: str, content: str):
        """Message should be immutable (frozen dataclass)."""
        msg = Message(role=role, content=content)

        # Attempting to modify should raise
        try:
            msg.role = "other"  # type: ignore
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass  # Expected for frozen dataclass

    @given(content=st.text(max_size=500))
    def test_assistant_message_with_tool_calls(self, content: str):
        """Assistant messages can have tool_calls."""
        tc = ToolCall.create("test_tool", {"arg": "value"})
        msg = Message(role="assistant", content=content, tool_calls=[tc])

        openai_fmt = msg.to_openai_format()
        assert "tool_calls" in openai_fmt
        assert len(openai_fmt["tool_calls"]) == 1

    @given(role=roles, content=st.text(max_size=500))
    def test_message_equality(self, role: str, content: str):
        """Messages with same values should be equal."""
        msg1 = Message(role=role, content=content)
        msg2 = Message(role=role, content=content)
        assert msg1 == msg2


# =============================================================================
# ToolCall Property Tests
# =============================================================================


class TestToolCallProperties:
    """Property-based tests for ToolCall type."""

    @given(name=tool_names, arguments=json_dicts)
    def test_toolcall_create_generates_id(self, name: str, arguments: dict[str, Any]):
        """ToolCall.create should generate unique IDs."""
        tc1 = ToolCall.create(name, arguments)
        tc2 = ToolCall.create(name, arguments)

        assert tc1.id != tc2.id
        assert tc1.id.startswith("call_")
        assert tc2.id.startswith("call_")

    @given(name=tool_names, arguments=json_dicts)
    def test_toolcall_arguments_json_roundtrip(
        self, name: str, arguments: dict[str, Any]
    ):
        """ToolCall arguments should roundtrip through JSON."""
        tc = ToolCall.create(name, arguments)

        # arguments_json should be valid JSON
        parsed = json.loads(tc.arguments_json)
        assert parsed == arguments

    @given(name=tool_names, arguments=json_dicts)
    def test_toolcall_preserves_name_and_arguments(
        self, name: str, arguments: dict[str, Any]
    ):
        """ToolCall should preserve name and arguments."""
        tc = ToolCall.create(name, arguments)

        assert tc.name == name
        assert tc.arguments == arguments

    @given(name=tool_names, arguments=json_dicts)
    def test_toolcall_in_message_openai_format(
        self, name: str, arguments: dict[str, Any]
    ):
        """ToolCall in Message should produce correct OpenAI format."""
        tc = ToolCall.create(name, arguments)
        msg = Message(role="assistant", content=None, tool_calls=[tc])
        fmt = msg.to_openai_format()

        assert "tool_calls" in fmt
        assert len(fmt["tool_calls"]) == 1
        tool_call_fmt = fmt["tool_calls"][0]
        assert tool_call_fmt["id"] == tc.id
        assert tool_call_fmt["type"] == "function"
        assert tool_call_fmt["function"]["name"] == name
        assert json.loads(tool_call_fmt["function"]["arguments"]) == arguments


# =============================================================================
# ToolResult Property Tests
# =============================================================================


class TestToolResultProperties:
    """Property-based tests for ToolResult type."""

    @given(
        call_id=call_ids,
        name=tool_names,
        output=st.text(max_size=500),
        is_error=st.booleans(),
    )
    def test_toolresult_to_message_format(
        self, call_id: str, name: str, output: str, is_error: bool
    ):
        """ToolResult.to_message should produce valid Message."""
        tr = ToolResult(call_id=call_id, name=name, output=output, is_error=is_error)
        msg = tr.to_message()

        assert msg.role == "tool"
        assert msg.content == output
        assert msg.tool_call_id == call_id
        assert msg.name == name

    @given(
        call_id=call_ids,
        name=tool_names,
        output=st.text(max_size=500),
    )
    def test_toolresult_is_error_flag(self, call_id: str, name: str, output: str):
        """ToolResult is_error flag should be preserved."""
        tr_ok = ToolResult(call_id=call_id, name=name, output=output, is_error=False)
        tr_err = ToolResult(call_id=call_id, name=name, output=output, is_error=True)

        assert tr_ok.is_error is False
        assert tr_err.is_error is True
        # Both should have same output regardless of is_error
        assert tr_ok.output == output
        assert tr_err.output == output


# =============================================================================
# ToolSchema Property Tests
# =============================================================================


class TestToolSchemaProperties:
    """Property-based tests for ToolSchema type."""

    @given(
        name=tool_names,
        description=st.text(min_size=1, max_size=200),
    )
    def test_toolschema_openai_format_structure(self, name: str, description: str):
        """ToolSchema OpenAI format should have correct structure."""
        params = {"type": "object", "properties": {}}
        ts = ToolSchema(name=name, description=description, parameters=params)
        fmt = ts.to_openai_format()

        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == name
        assert fmt["function"]["description"] == description
        assert fmt["function"]["parameters"] == params

    @given(name=tool_names, description=st.text(min_size=1, max_size=200))
    def test_toolschema_equality(self, name: str, description: str):
        """ToolSchemas with same values should be equal."""
        params = {"type": "object"}
        ts1 = ToolSchema(name=name, description=description, parameters=params)
        ts2 = ToolSchema(name=name, description=description, parameters=params)
        assert ts1 == ts2


# =============================================================================
# TokenUsage Property Tests
# =============================================================================


class TestTokenUsageProperties:
    """Property-based tests for TokenUsage type."""

    @given(
        prompt=st.integers(min_value=0, max_value=100000),
        completion=st.integers(min_value=0, max_value=100000),
    )
    def test_token_usage_total_consistency(self, prompt: int, completion: int):
        """TokenUsage total should equal prompt + completion."""
        total = prompt + completion
        usage = TokenUsage(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
        )

        assert usage.prompt_tokens == prompt
        assert usage.completion_tokens == completion
        assert usage.total_tokens == total

    @given(
        prompt=st.integers(min_value=0, max_value=100000),
        completion=st.integers(min_value=0, max_value=100000),
    )
    def test_token_usage_immutability(self, prompt: int, completion: int):
        """TokenUsage should be immutable."""
        usage = TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )

        try:
            usage.prompt_tokens = 999  # type: ignore
            assert False, "Should have raised"
        except AttributeError:
            pass  # Expected
