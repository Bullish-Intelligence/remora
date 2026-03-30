"""Shared test fixtures for structured-agents."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from structured_agents.client.protocol import CompletionResponse
from structured_agents.parsing import DefaultResponseParser
from structured_agents.types import (
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
)


@pytest.fixture
def mock_client():
    """A mock LLM client that returns configurable responses."""
    client = AsyncMock()
    client.model = "test-model"
    client.chat_completion = AsyncMock(
        return_value=CompletionResponse(
            content="Hello",
            tool_calls=None,
            usage=None,
            finish_reason="stop",
            raw_response={},
        )
    )
    client.close = AsyncMock()
    return client


@pytest.fixture
def response_parser():
    """A DefaultResponseParser instance."""
    return DefaultResponseParser()


@pytest.fixture
def sample_messages():
    """Standard system + user message pair."""
    return [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hello"),
    ]


@pytest.fixture
def sample_tool_schema():
    """A simple tool schema for testing."""
    return ToolSchema(
        name="add_numbers",
        description="Add two numbers",
        parameters={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    )


@pytest.fixture
def sample_tool_call():
    """A sample tool call."""
    return ToolCall(id="call_abc123", name="add_numbers", arguments={"x": 1, "y": 2})
