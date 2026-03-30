"""End-to-end integration tests for the structured-agents kernel loop.

These tests exercise the full agent loop with mocked LLM responses to verify:
- Tool execution flow
- Event emission
- Response parsing
- Multi-turn conversations
- Error handling
- Grammar constraint application
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from structured_agents import (
    AgentKernel,
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
    DefaultResponseParser,
    DecodingConstraint,
    Tool,
    KernelEvent,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.client.protocol import CompletionResponse
from structured_agents.grammar.pipeline import ConstraintPipeline


# =============================================================================
# Test Fixtures and Helpers
# =============================================================================


@dataclass
class MockLLMClient:
    """Mock LLM client that returns predefined responses."""

    model: str = "test-model"
    responses: list[CompletionResponse] = field(default_factory=list)
    call_count: int = 0
    last_messages: list[dict[str, Any]] | None = None
    last_tools: list[dict[str, Any]] | None = None
    last_extra_body: dict[str, Any] | None = None

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> CompletionResponse:
        self.last_messages = messages
        self.last_tools = tools
        self.last_extra_body = extra_body

        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response

        # Default: return empty response (no tool calls)
        return CompletionResponse(
            content="Done",
            tool_calls=None,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
            raw_response={},
        )

    async def close(self) -> None:
        pass


def make_completion_response(
    content: str | None = None,
    tool_calls: list[ToolCall] | None = None,
) -> CompletionResponse:
    """Helper to create CompletionResponse."""
    api_tool_calls = None
    if tool_calls:
        api_tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments_json},
            }
            for tc in tool_calls
        ]
    return CompletionResponse(
        content=content,
        tool_calls=api_tool_calls,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        finish_reason="stop",
        raw_response={},
    )


@dataclass
class CalculatorTool(Tool):
    """Simple calculator tool for testing."""

    operations: list[str] = field(default_factory=list)

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculate",
            description="Perform a calculation",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "multiply", "subtract"],
                    },
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["operation", "a", "b"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        op = arguments.get("operation", "add")
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)

        self.operations.append(f"{op}({a}, {b})")

        if op == "add":
            result = a + b
        elif op == "multiply":
            result = a * b
        elif op == "subtract":
            result = a - b
        else:
            return ToolResult(
                call_id=context.id if context else "",
                name=self.schema.name,
                output=f"Unknown operation: {op}",
                is_error=True,
            )

        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=json.dumps({"result": result}),
            is_error=False,
        )


@dataclass
class FailingTool(Tool):
    """Tool that always fails."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="fail",
            description="Always fails",
            parameters={"type": "object", "properties": {}},
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output="Intentional failure",
            is_error=True,
        )


@dataclass
class ExceptionTool(Tool):
    """Tool that raises an exception."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="explode",
            description="Raises an exception",
            parameters={"type": "object", "properties": {}},
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        raise RuntimeError("Tool exploded!")


class EventCollector:
    """Observer that collects all events."""

    def __init__(self):
        self.events: list[KernelEvent] = []

    async def emit(self, event: KernelEvent) -> None:
        self.events.append(event)

    def get_events_by_type(self, event_type: type) -> list[KernelEvent]:
        return [e for e in self.events if isinstance(e, event_type)]


# =============================================================================
# Single Turn Tests
# =============================================================================


class TestSingleTurnExecution:
    """Tests for single-turn kernel execution."""

    async def test_simple_response_no_tools(self):
        """Kernel should handle simple response without tool calls."""
        client = MockLLMClient(
            model="test-model",
            responses=[make_completion_response(content="Hello, world!")],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[],
        )

        messages = [Message(role="user", content="Say hello")]
        result = await kernel.run(messages, [], max_turns=3)

        assert result.turn_count == 1
        assert result.termination_reason == "no_tool_calls"
        assert result.final_message.content == "Hello, world!"

    async def test_single_tool_call_execution(self):
        """Kernel should execute a single tool call."""
        tool_call = ToolCall.create("calculate", {"operation": "add", "a": 5, "b": 3})
        calc_tool = CalculatorTool()

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[tool_call]),
                make_completion_response(content="The result is 8"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
        )

        messages = [Message(role="user", content="Add 5 and 3")]
        result = await kernel.run(messages, [calc_tool.schema], max_turns=3)

        assert result.turn_count == 2
        assert "8" in result.final_message.content
        assert calc_tool.operations == ["add(5, 3)"]


# =============================================================================
# Multi-Turn Tests
# =============================================================================


class TestMultiTurnExecution:
    """Tests for multi-turn kernel execution."""

    async def test_chained_tool_calls(self):
        """Kernel should handle chained tool calls across turns."""
        calc_tool = CalculatorTool()

        # Turn 1: add 5 + 3
        call1 = ToolCall.create("calculate", {"operation": "add", "a": 5, "b": 3})
        # Turn 2: multiply result by 2
        call2 = ToolCall.create("calculate", {"operation": "multiply", "a": 8, "b": 2})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call1]),
                make_completion_response(tool_calls=[call2]),
                make_completion_response(content="Final result is 16"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
        )

        messages = [Message(role="user", content="Add 5+3 then multiply by 2")]
        result = await kernel.run(messages, [calc_tool.schema], max_turns=5)

        assert result.turn_count == 3
        assert calc_tool.operations == ["add(5, 3)", "multiply(8, 2)"]
        assert "16" in result.final_message.content

    async def test_max_turns_limit(self):
        """Kernel should stop at max_turns even if tools keep being called."""
        calc_tool = CalculatorTool()
        call = ToolCall.create("calculate", {"operation": "add", "a": 1, "b": 1})

        # Always return tool calls
        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(tool_calls=[call]),
                make_completion_response(tool_calls=[call]),
                make_completion_response(tool_calls=[call]),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
        )

        messages = [Message(role="user", content="Keep calculating")]
        result = await kernel.run(messages, [calc_tool.schema], max_turns=2)

        assert result.turn_count == 2
        assert result.termination_reason == "max_turns"


# =============================================================================
# Event Emission Tests
# =============================================================================


class TestEventEmission:
    """Tests for kernel event emission."""

    async def test_complete_event_sequence(self):
        """Kernel should emit all events in correct sequence."""
        collector = EventCollector()
        calc_tool = CalculatorTool()
        call = ToolCall.create("calculate", {"operation": "add", "a": 1, "b": 2})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(content="Done"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
            observer=collector,
        )

        messages = [Message(role="user", content="Calculate")]
        await kernel.run(messages, [calc_tool.schema], max_turns=3)

        # Check event types
        event_types = [type(e).__name__ for e in collector.events]

        assert "KernelStartEvent" in event_types
        assert "ModelRequestEvent" in event_types
        assert "ModelResponseEvent" in event_types
        assert "ToolCallEvent" in event_types
        assert "ToolResultEvent" in event_types
        assert "TurnCompleteEvent" in event_types
        assert "KernelEndEvent" in event_types

        # Check sequence: KernelStartEvent first, KernelEndEvent last
        assert isinstance(collector.events[0], KernelStartEvent)
        assert isinstance(collector.events[-1], KernelEndEvent)

    async def test_no_duplicate_model_request_events(self):
        """Kernel should not emit duplicate ModelRequestEvent per turn."""
        collector = EventCollector()

        client = MockLLMClient(
            model="test-model",
            responses=[make_completion_response(content="Hello")],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[],
            observer=collector,
        )

        messages = [Message(role="user", content="Hi")]
        await kernel.run(messages, [], max_turns=1)

        model_requests = collector.get_events_by_type(ModelRequestEvent)
        assert len(model_requests) == 1

    async def test_tool_events_contain_correct_data(self):
        """Tool events should contain correct tool name and arguments."""
        collector = EventCollector()
        calc_tool = CalculatorTool()
        call = ToolCall.create("calculate", {"operation": "multiply", "a": 3, "b": 4})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(content="12"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
            observer=collector,
        )

        messages = [Message(role="user", content="Multiply")]
        await kernel.run(messages, [calc_tool.schema], max_turns=3)

        tool_call_events = collector.get_events_by_type(ToolCallEvent)
        assert len(tool_call_events) == 1
        assert tool_call_events[0].tool_name == "calculate"
        assert tool_call_events[0].arguments["operation"] == "multiply"

        tool_result_events = collector.get_events_by_type(ToolResultEvent)
        assert len(tool_result_events) == 1
        assert tool_result_events[0].is_error is False


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in kernel."""

    async def test_tool_error_result_handling(self):
        """Kernel should handle tools that return errors."""
        collector = EventCollector()
        fail_tool = FailingTool()
        call = ToolCall.create("fail", {})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(content="I see the tool failed"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[fail_tool],
            observer=collector,
        )

        messages = [Message(role="user", content="Fail")]
        result = await kernel.run(messages, [fail_tool.schema], max_turns=3)

        # Should complete without crashing
        assert result.turn_count == 2

        # Error should be recorded in events
        tool_result_events = collector.get_events_by_type(ToolResultEvent)
        assert len(tool_result_events) == 1
        assert tool_result_events[0].is_error is True

    async def test_unknown_tool_handling(self):
        """Kernel should handle calls to unknown tools gracefully."""
        collector = EventCollector()
        call = ToolCall.create("nonexistent_tool", {"arg": "value"})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(content="Tool not found"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[],  # No tools registered
            observer=collector,
        )

        messages = [Message(role="user", content="Call unknown")]
        result = await kernel.run(messages, [], max_turns=3)

        # Should complete
        assert result.turn_count >= 1

        # Should have error in results
        tool_result_events = collector.get_events_by_type(ToolResultEvent)
        if tool_result_events:
            assert tool_result_events[0].is_error is True

    async def test_tool_exception_handling(self):
        """Kernel should handle tools that raise exceptions."""
        collector = EventCollector()
        explode_tool = ExceptionTool()
        call = ToolCall.create("explode", {})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(content="Something went wrong"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[explode_tool],
            observer=collector,
        )

        messages = [Message(role="user", content="Explode")]
        result = await kernel.run(messages, [explode_tool.schema], max_turns=3)

        # Should complete without crashing the kernel
        assert result.turn_count >= 1


# =============================================================================
# Grammar Constraint Tests
# =============================================================================


class TestGrammarConstraints:
    """Tests for grammar constraint application."""

    async def test_constraints_applied_for_hosted_vllm(self):
        """Grammar constraints should be applied for hosted_vllm models."""
        client = MockLLMClient(
            model="hosted_vllm/Qwen/Qwen3-4B",
            responses=[make_completion_response(content="Done")],
        )

        constraint = DecodingConstraint(
            strategy="structural_tag", allow_parallel_calls=True
        )
        pipeline = ConstraintPipeline(constraint)

        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            constraint_pipeline=pipeline,
            tools=[],
        )

        calc_tool = CalculatorTool()
        messages = [Message(role="user", content="Test")]
        await kernel.run(messages, [calc_tool.schema], max_turns=1)

        # Check that extra_body was passed to client
        assert client.last_extra_body is not None
        assert "structured_outputs" in client.last_extra_body

    async def test_constraints_not_applied_for_anthropic(self):
        """Grammar constraints should NOT be applied for anthropic models."""
        client = MockLLMClient(
            model="anthropic/claude-3-sonnet",
            responses=[make_completion_response(content="Done")],
        )

        constraint = DecodingConstraint(
            strategy="structural_tag", allow_parallel_calls=True
        )
        pipeline = ConstraintPipeline(constraint)

        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            constraint_pipeline=pipeline,
            tools=[],
        )

        calc_tool = CalculatorTool()
        messages = [Message(role="user", content="Test")]
        await kernel.run(messages, [calc_tool.schema], max_turns=1)

        # extra_body should be None for non-vllm providers
        assert client.last_extra_body is None

    async def test_constraints_not_applied_for_openai(self):
        """Grammar constraints should NOT be applied for openai models."""
        client = MockLLMClient(
            model="openai/gpt-4o",
            responses=[make_completion_response(content="Done")],
        )

        constraint = DecodingConstraint(
            strategy="structural_tag", allow_parallel_calls=True
        )
        pipeline = ConstraintPipeline(constraint)

        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            constraint_pipeline=pipeline,
            tools=[],
        )

        calc_tool = CalculatorTool()
        messages = [Message(role="user", content="Test")]
        await kernel.run(messages, [calc_tool.schema], max_turns=1)

        # extra_body should be None for non-vllm providers
        assert client.last_extra_body is None


# =============================================================================
# XML Tool Call Parsing Tests
# =============================================================================


class TestXMLToolCallParsing:
    """Tests for XML tool call parsing in responses."""

    async def test_xml_tool_call_in_content(self):
        """Kernel should parse XML tool calls from content."""
        calc_tool = CalculatorTool()

        # Response with XML tool call in content (not native tool_calls)
        xml_content = (
            "Let me calculate that.\n"
            '<tool_call>{"name": "calculate", "arguments": {"operation": "add", "a": 10, "b": 20}}</tool_call>'
        )

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(content=xml_content),
                make_completion_response(content="The result is 30"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
        )

        messages = [Message(role="user", content="Add 10 and 20")]
        result = await kernel.run(messages, [calc_tool.schema], max_turns=3)

        # Tool should have been executed
        assert calc_tool.operations == ["add(10, 20)"]
        assert "30" in result.final_message.content


# =============================================================================
# Conversation History Tests
# =============================================================================


class TestConversationHistory:
    """Tests for conversation history management."""

    async def test_history_includes_all_messages(self):
        """Result history should include all messages from conversation."""
        calc_tool = CalculatorTool()
        call = ToolCall.create("calculate", {"operation": "add", "a": 1, "b": 1})

        client = MockLLMClient(
            model="test-model",
            responses=[
                make_completion_response(tool_calls=[call]),
                make_completion_response(content="Result is 2"),
            ],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[calc_tool],
        )

        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Add 1+1"),
        ]
        result = await kernel.run(messages, [calc_tool.schema], max_turns=3)

        # History should include: system, user, assistant (with tool call), tool result, assistant (final)
        roles = [m.role for m in result.history]
        assert "system" in roles
        assert "user" in roles
        assert "assistant" in roles
        assert "tool" in roles

    async def test_final_message_is_last_assistant(self):
        """Final message should be the last assistant message."""
        client = MockLLMClient(
            model="test-model",
            responses=[make_completion_response(content="Final answer")],
        )
        kernel = AgentKernel(
            client=client,
            response_parser=DefaultResponseParser(),
            tools=[],
        )

        messages = [Message(role="user", content="Question")]
        result = await kernel.run(messages, [], max_turns=1)

        assert result.final_message.role == "assistant"
        assert result.final_message.content == "Final answer"
