# tests/test_kernel/test_kernel_comprehensive.py
"""Comprehensive tests for AgentKernel."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from structured_agents.kernel import AgentKernel, _supports_grammar_constraints
from structured_agents.parsing import DefaultResponseParser
from structured_agents.grammar import ConstraintPipeline, DecodingConstraint
from structured_agents.tools.protocol import Tool
from structured_agents.types import ToolSchema, ToolResult, Message, TokenUsage
from structured_agents.client.protocol import CompletionResponse
from structured_agents.events import (
    NullObserver,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)


class TestGrammarConstraintDetection:
    """Tests for provider-aware grammar constraint detection."""

    def test_supports_hosted_vllm(self):
        """hosted_vllm/ prefix should support grammar constraints."""
        assert _supports_grammar_constraints("hosted_vllm/Qwen/Qwen3-4B") is True
        assert (
            _supports_grammar_constraints("hosted_vllm/meta-llama/Meta-Llama-3.1-8B")
            is True
        )

    def test_does_not_support_anthropic(self):
        """anthropic/ prefix should not support grammar constraints."""
        assert _supports_grammar_constraints("anthropic/claude-3-opus") is False

    def test_does_not_support_openai(self):
        """openai/ prefix should not support grammar constraints."""
        assert _supports_grammar_constraints("openai/gpt-4-turbo") is False

    def test_does_not_support_plain_model(self):
        """Plain model names should not support grammar constraints."""
        assert _supports_grammar_constraints("Qwen/Qwen3-4B") is False


class TestKernelWithTools:
    """Tests for kernel tool execution."""

    @pytest.mark.asyncio
    async def test_kernel_executes_tool_calls(self):
        """Kernel should execute tool calls and return results."""
        mock_client = AsyncMock()
        mock_client.model = "test-model"
        mock_client.chat_completion = AsyncMock(
            return_value=CompletionResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "add",
                            "arguments": '{"x": 2, "y": 3}',
                        },
                    }
                ],
                usage=TokenUsage(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
                finish_reason="tool_calls",
                raw_response={},
            )
        )
        mock_client.close = AsyncMock()

        mock_tool = MagicMock(spec=Tool)
        mock_tool.schema = ToolSchema(
            name="add",
            description="Add two numbers",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "int"}, "y": {"type": "int"}},
            },
        )
        mock_tool.execute = AsyncMock(
            return_value=ToolResult(
                call_id="call_123", name="add", output="5", is_error=False
            )
        )

        kernel = AgentKernel(
            client=mock_client,
            response_parser=DefaultResponseParser(),
            tools=[mock_tool],
        )

        messages = [Message(role="user", content="What is 2 + 3?")]
        result = await kernel.step(messages, tools=[mock_tool.schema])

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "add"
        assert result.tool_calls[0].arguments == {"x": 2, "y": 3}
        assert len(result.tool_results) == 1
        assert result.tool_results[0].output == "5"
        mock_tool.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_kernel_handles_unknown_tool(self):
        """Kernel should gracefully handle calls to unknown tools."""
        mock_client = AsyncMock()
        mock_client.model = "test-model"
        mock_client.chat_completion = AsyncMock(
            return_value=CompletionResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "unknown_tool",
                            "arguments": "{}",
                        },
                    }
                ],
                usage=None,
                finish_reason="tool_calls",
                raw_response={},
            )
        )
        mock_client.close = AsyncMock()

        kernel = AgentKernel(
            client=mock_client,
            response_parser=DefaultResponseParser(),
            tools=[],  # No tools registered
        )

        messages = [Message(role="user", content="Call unknown")]
        result = await kernel.step(messages, tools=[])

        assert len(result.tool_results) == 1
        assert result.tool_results[0].is_error is True
        assert "Unknown tool" in result.tool_results[0].output


class TestKernelEventEmission:
    """Tests for kernel event emission."""

    @pytest.mark.asyncio
    async def test_kernel_emits_events_on_step(self):
        """Kernel should emit correct events during step."""
        events_received = []

        class CollectingObserver:
            async def emit(self, event):
                events_received.append(event)

        mock_client = AsyncMock()
        mock_client.model = "test-model"
        mock_client.chat_completion = AsyncMock(
            return_value=CompletionResponse(
                content="Hello",
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
                finish_reason="stop",
                raw_response={},
            )
        )
        mock_client.close = AsyncMock()

        kernel = AgentKernel(
            client=mock_client,
            response_parser=DefaultResponseParser(),
            tools=[],
            observer=CollectingObserver(),
        )

        messages = [Message(role="user", content="Hello")]
        await kernel.step(messages, tools=[])

        # Should have: ModelRequestEvent, ModelResponseEvent, TurnCompleteEvent
        assert len(events_received) == 3
        assert isinstance(events_received[0], ModelRequestEvent)
        assert isinstance(events_received[1], ModelResponseEvent)
        assert isinstance(events_received[2], TurnCompleteEvent)

    @pytest.mark.asyncio
    async def test_kernel_emits_no_duplicate_model_request_in_run(self):
        """Bug fix: ModelRequestEvent should only be emitted once per turn."""
        events_received = []

        class CollectingObserver:
            async def emit(self, event):
                events_received.append(event)

        mock_client = AsyncMock()
        mock_client.model = "test-model"
        mock_client.chat_completion = AsyncMock(
            return_value=CompletionResponse(
                content="Done",
                tool_calls=None,
                usage=None,
                finish_reason="stop",
                raw_response={},
            )
        )
        mock_client.close = AsyncMock()

        kernel = AgentKernel(
            client=mock_client,
            response_parser=DefaultResponseParser(),
            tools=[],
            observer=CollectingObserver(),
        )

        messages = [Message(role="user", content="Hello")]
        await kernel.run(messages, tools=[], max_turns=1)

        # Count ModelRequestEvents - should be exactly 1
        model_request_events = [
            e for e in events_received if isinstance(e, ModelRequestEvent)
        ]
        assert len(model_request_events) == 1, (
            f"Expected 1 ModelRequestEvent, got {len(model_request_events)}"
        )


class TestKernelWithConstraintPipeline:
    """Tests for kernel with constraint pipeline."""

    @pytest.mark.asyncio
    async def test_kernel_applies_constraints_for_hosted_vllm(self):
        """Constraints should be applied for hosted_vllm models."""
        mock_client = AsyncMock()
        mock_client.model = "hosted_vllm/Qwen/Qwen3-4B"
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

        constraint = DecodingConstraint(strategy="structural_tag")
        pipeline = ConstraintPipeline(constraint)

        tool_schema = ToolSchema(
            name="test",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
        )

        kernel = AgentKernel(
            client=mock_client,
            response_parser=DefaultResponseParser(),
            tools=[],
            constraint_pipeline=pipeline,
        )

        messages = [Message(role="user", content="Hello")]
        await kernel.step(messages, tools=[tool_schema])

        # Verify extra_body was passed
        call_kwargs = mock_client.chat_completion.call_args.kwargs
        assert "extra_body" in call_kwargs
        assert call_kwargs["extra_body"] is not None

    @pytest.mark.asyncio
    async def test_kernel_does_not_apply_constraints_for_anthropic(self):
        """Constraints should NOT be applied for non-vLLM providers."""
        mock_client = AsyncMock()
        mock_client.model = "anthropic/claude-3-opus"
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

        constraint = DecodingConstraint(strategy="structural_tag")
        pipeline = ConstraintPipeline(constraint)

        tool_schema = ToolSchema(
            name="test",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
        )

        kernel = AgentKernel(
            client=mock_client,
            response_parser=DefaultResponseParser(),
            tools=[],
            constraint_pipeline=pipeline,
        )

        messages = [Message(role="user", content="Hello")]
        await kernel.step(messages, tools=[tool_schema])

        # Verify extra_body is None for non-vLLM providers
        call_kwargs = mock_client.chat_completion.call_args.kwargs
        assert call_kwargs.get("extra_body") is None
