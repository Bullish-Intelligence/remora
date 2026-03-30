# tests/test_integration/test_full_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from structured_agents import AgentKernel
from structured_agents.parsing import DefaultResponseParser
from structured_agents.tools import Tool
from structured_agents.types import Message, ToolSchema, ToolResult, TokenUsage
from structured_agents.client.protocol import CompletionResponse


@pytest.mark.asyncio
async def test_full_agent_loop():
    """End-to-end test of agent running one turn."""

    mock_client = AsyncMock()
    mock_client.model = "test-model"

    # First call returns tool call, second call returns final answer
    call_count = 0

    async def mock_completion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CompletionResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "add",
                            "arguments": '{"a": 1, "b": 2}',
                        },
                    }
                ],
                usage=TokenUsage(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
                finish_reason="tool_calls",
                raw_response={},
            )
        else:
            return CompletionResponse(
                content="The result is 3.",
                tool_calls=None,
                usage=TokenUsage(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
                finish_reason="stop",
                raw_response={},
            )

    mock_client.chat_completion = AsyncMock(side_effect=mock_completion)
    mock_client.close = AsyncMock()

    mock_tool = MagicMock(spec=Tool)
    mock_tool.schema = ToolSchema(
        name="add",
        description="Add two numbers",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "int"}, "b": {"type": "int"}},
        },
    )
    mock_tool.execute = AsyncMock(
        return_value=ToolResult(
            call_id="call_123", name="add", output='{"result": 3}', is_error=False
        )
    )

    response_parser = DefaultResponseParser()

    kernel = AgentKernel(
        client=mock_client,
        response_parser=response_parser,
        tools=[mock_tool],
    )

    messages = [
        Message(role="system", content="You are a calculator."),
        Message(role="user", content="What is 1 + 2?"),
    ]

    result = await kernel.run(messages, [mock_tool.schema], max_turns=2)

    assert result.turn_count == 2
    assert result.termination_reason == "no_tool_calls"

    mock_tool.execute.assert_called_once()

    await kernel.close()
