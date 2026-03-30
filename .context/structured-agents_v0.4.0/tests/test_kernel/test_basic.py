# tests/test_kernel/test_basic.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from structured_agents.kernel import AgentKernel
from structured_agents.parsing import DefaultResponseParser
from structured_agents.tools.protocol import Tool
from structured_agents.types import ToolSchema, ToolResult, Message
from structured_agents.client.protocol import CompletionResponse


@pytest.mark.asyncio
async def test_kernel_step_basic():
    # Setup mocks
    mock_client = AsyncMock()
    mock_client.model = "test-model"
    mock_client.chat_completion = AsyncMock(
        return_value=CompletionResponse(
            content="Hello",
            tool_calls=None,
            usage=None,
            finish_reason="stop",
            raw_response={},
        )
    )
    mock_client.close = AsyncMock()

    response_parser = DefaultResponseParser()

    # Minimal tool
    mock_tool = MagicMock(spec=Tool)
    mock_tool.schema = ToolSchema(name="test", description="A test", parameters={})
    mock_tool.execute = AsyncMock(
        return_value=ToolResult(
            call_id="c1", name="test", output="result", is_error=False
        )
    )

    kernel = AgentKernel(
        client=mock_client,
        response_parser=response_parser,
        tools=[mock_tool],
    )

    messages = [Message(role="user", content="Hello")]
    result = await kernel.step(messages, tools=[mock_tool.schema])

    assert result.response_message.content == "Hello"
