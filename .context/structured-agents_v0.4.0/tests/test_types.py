# tests/test_types.py
import pytest
from structured_agents.types import (
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
)


def test_message_creation():
    msg = Message(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"


def test_message_to_openai_format():
    msg = Message(role="user", content="Hello")
    assert msg.to_openai_format() == {"role": "user", "content": "Hello"}


def test_tool_call_create():
    tc = ToolCall.create("add", {"a": 1, "b": 2})
    assert tc.name == "add"
    assert tc.arguments == {"a": 1, "b": 2}
    assert tc.id.startswith("call_")


def test_tool_result_error_property():
    result = ToolResult(call_id="call_123", name="add", output="error", is_error=True)
    assert result.is_error == True
