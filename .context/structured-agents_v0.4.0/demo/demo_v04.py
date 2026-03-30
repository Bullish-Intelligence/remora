#!/usr/bin/env python3
"""
structured-agents v0.4.0 Demo

This demo demonstrates all core functionality of the structured-agents library:
- Tool protocol for custom tools
- ResponseParser for model-specific behavior
- DecodingConstraint for grammar-constrained decoding
- AgentKernel for the core agent loop
- Unified event system with Observer protocol
- LLMClient for API connections (OpenAI and LiteLLM)

The demo runs against a real vLLM server at remora-server:8000 with the Qwen model.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from structured_agents.grammar.pipeline import ConstraintPipeline

# =============================================================================
# IMPORTS - All v0.4.0 Core Concepts
# =============================================================================

from structured_agents import (
    # Types
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
    StepResult,
    RunResult,
    # Tools
    Tool,
    # Parsing (replaces ModelAdapter)
    ResponseParser,
    DefaultResponseParser,
    # Grammar
    DecodingConstraint,
    StructuredOutputModel,
    # Events
    Observer,
    NullObserver,
    KernelEvent,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    # Core
    AgentKernel,
    # Client
    LLMClient,
    OpenAICompatibleClient,
    build_client,
)


# =============================================================================
# STEP 1: Define Custom Tools (native Python, no .pym)
# =============================================================================


@dataclass
class AddTool(Tool):
    """Tool that adds two numbers."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="add",
            description="Add two numbers together",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        result = a + b
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=json.dumps({"result": result}),
            is_error=False,
        )


@dataclass
class MultiplyTool(Tool):
    """Tool that multiplies two numbers."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="multiply",
            description="Multiply two numbers together",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        result = a * b
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=json.dumps({"result": result}),
            is_error=False,
        )


def build_demo_tools() -> list[Tool]:
    """Build list of demo tools."""
    return [AddTool(), MultiplyTool()]


# =============================================================================
# STEP 2: Custom Event Observer
# =============================================================================


class DemoObserver:
    """Observer that prints events during agent execution."""

    async def emit(self, event: KernelEvent) -> None:
        if isinstance(event, KernelStartEvent):
            print(
                f"\n[KERNEL START] max_turns={event.max_turns}, tools={event.tools_count}"
            )
        elif isinstance(event, KernelEndEvent):
            print(
                f"[KERNEL END] turns={event.turn_count}, reason={event.termination_reason}"
            )
        elif isinstance(event, ModelRequestEvent):
            print(f"  [MODEL REQUEST] Turn {event.turn}: {event.model}")
        elif isinstance(event, ModelResponseEvent):
            print(
                f"  [MODEL RESPONSE] Turn {event.turn}: content={event.content[:50] if event.content else 'None'}..., tools={event.tool_calls_count}"
            )
        elif isinstance(event, ToolCallEvent):
            print(f"    [TOOL CALL] {event.tool_name}({json.dumps(event.arguments)})")
        elif isinstance(event, ToolResultEvent):
            status = "ERROR" if event.is_error else "OK"
            preview = event.output_preview[:30] if event.output_preview else ""
            print(f"    [TOOL RESULT] {event.tool_name}: {status} - {preview}...")
        elif isinstance(event, TurnCompleteEvent):
            print(
                f"  [TURN COMPLETE] Turn {event.turn}: {event.tool_calls_count} calls, {event.errors_count} errors"
            )


# =============================================================================
# STEP 3: Demo - Direct Kernel Usage
# =============================================================================


async def demo_kernel_direct():
    """Demonstrate direct Kernel usage."""
    print("\n" + "=" * 60)
    print("DEMO 1: Direct AgentKernel Usage")
    print("=" * 60)

    # Build tools
    print("\n[Step 1] Building tools...")
    tools = build_demo_tools()
    print(f"  Found {len(tools)} tools: {[t.schema.name for t in tools]}")

    # Build client with v0.4 LiteLLM routing
    print("\n[Step 2] Building LLM client...")
    model_name = "hosted_vllm/Qwen/Qwen3-4B-Instruct-2507-FP8"
    client = build_client(
        {
            "base_url": "http://remora-server:8000/v1",
            "api_key": "EMPTY",
            "model": model_name,
            "timeout": 120.0,
        }
    )

    # Build constraint pipeline
    print("\n[Step 3] Building ConstraintPipeline...")
    constraint = DecodingConstraint(
        strategy="structural_tag", allow_parallel_calls=True
    )
    pipeline = ConstraintPipeline(constraint)

    # Build kernel (v0.4 API - no adapter indirection)
    print("\n[Step 4] Building AgentKernel...")
    kernel = AgentKernel(
        client=client,
        model=model_name,
        response_parser=DefaultResponseParser(),
        constraint_pipeline=pipeline,
        tools=tools,
        observer=DemoObserver(),
        max_tokens=1024,
        temperature=0.1,
    )

    # Create messages
    print("\n[Step 5] Creating messages...")
    messages = [
        Message(
            role="system", content="You are a helpful assistant with access to tools."
        ),
        Message(role="user", content="What is 5 + 3? Use the add tool."),
    ]

    # Run the kernel
    print("\n[Step 6] Running kernel...")
    tool_schemas = [t.schema for t in tools]
    result = await kernel.run(messages, tool_schemas, max_turns=3)

    # Print results
    print("\n[Results]")
    print(f"  Turn count: {result.turn_count}")
    print(f"  Termination: {result.termination_reason}")
    print(f"  Final message: {result.final_message.content}")
    print(f"  History length: {len(result.history)}")

    # Cleanup
    await kernel.close()

    return result


# =============================================================================
# STEP 4: Demo - Event Types
# =============================================================================


async def demo_events():
    """Demonstrate the event system."""
    print("\n" + "=" * 60)
    print("DEMO 2: Event System")
    print("=" * 60)

    # Create some events
    events = [
        KernelStartEvent(max_turns=5, tools_count=3, initial_messages_count=2),
        ModelRequestEvent(turn=1, messages_count=3, tools_count=3, model="qwen"),
        ModelResponseEvent(
            turn=1, duration_ms=150, content="Hello", tool_calls_count=1, usage=None
        ),
        ToolCallEvent(
            turn=1, tool_name="add", call_id="call_123", arguments={"a": 1, "b": 2}
        ),
        ToolResultEvent(
            turn=1,
            tool_name="add",
            call_id="call_123",
            is_error=False,
            duration_ms=10,
            output_preview='{"sum": 3}',
        ),
        TurnCompleteEvent(
            turn=1, tool_calls_count=1, tool_results_count=1, errors_count=0
        ),
        KernelEndEvent(
            turn_count=1, termination_reason="no_tool_calls", total_duration_ms=200
        ),
    ]

    print("\n[Event Types]")
    for event in events:
        print(f"  {event.__class__.__name__}")

    # Demonstrate NullObserver
    print("\n[NullObserver Test]")
    null_obs = NullObserver()
    await null_obs.emit(
        KernelStartEvent(max_turns=1, tools_count=1, initial_messages_count=1)
    )
    print("  NullObserver works!")

    # Demonstrate Pydantic serialization (new in v0.4)
    print("\n[Pydantic Serialization (v0.4)]")
    event = ToolCallEvent(
        turn=1, tool_name="add", call_id="call_123", arguments={"a": 1, "b": 2}
    )
    print(f"  JSON: {event.model_dump_json()}")

    return events


# =============================================================================
# STEP 5: Demo - Grammar/Constraint Pipeline
# =============================================================================


def demo_grammar_pipeline():
    """Demonstrate the grammar constraint pipeline."""
    print("\n" + "=" * 60)
    print("DEMO 3: Grammar/Constraint Pipeline")
    print("=" * 60)

    class SimpleStructuredOutput(StructuredOutputModel):
        value: int
        note: str

    constraint = DecodingConstraint(
        strategy="json_schema",
        allow_parallel_calls=False,
        send_tools_to_api=False,
        schema_model=SimpleStructuredOutput,
    )
    schema_name = (
        constraint.schema_model.__name__ if constraint.schema_model else "None"
    )
    print(f"\n[DecodingConstraint]")
    print(f"  strategy: {constraint.strategy}")
    print(f"  schema_model: {schema_name}")

    pipeline = ConstraintPipeline(constraint)

    tools = [
        ToolSchema(
            name="add", description="Add two numbers", parameters={"type": "object"}
        ),
        ToolSchema(
            name="multiply",
            description="Multiply two numbers",
            parameters={"type": "object"},
        ),
    ]

    result = pipeline.constrain(tools)
    print(f"\n[ConstraintPipeline JSON]")
    print(f"  Result keys: {list(result.keys()) if result else None}")

    empty_result = pipeline.constrain([])
    print(f"  Empty tools result: {empty_result}")

    structural_constraint = DecodingConstraint(
        strategy="structural_tag", allow_parallel_calls=True
    )
    structural_pipeline = ConstraintPipeline(structural_constraint)
    structural_result = structural_pipeline.constrain(tools)
    print(f"\n[ConstraintPipeline Structural Tag]")
    print(
        f"  Result keys: {list(structural_result['structured_outputs'].keys()) if structural_result else None}"
    )

    return pipeline


# =============================================================================
# STEP 6: Demo - Types and Core Classes
# =============================================================================


def demo_types():
    """Demonstrate core types."""
    print("\n" + "=" * 60)
    print("DEMO 4: Core Types")
    print("=" * 60)

    # Message
    msg = Message(role="user", content="Hello")
    print(f"\n[Message]")
    print(f"  role: {msg.role}")
    print(f"  content: {msg.content}")
    print(f"  to_openai_format(): {msg.to_openai_format()}")

    # ToolCall
    tc = ToolCall.create("add", {"a": 1, "b": 2})
    print(f"\n[ToolCall]")
    print(f"  id: {tc.id}")
    print(f"  name: {tc.name}")
    print(f"  arguments: {tc.arguments}")
    print(f"  arguments_json: {tc.arguments_json}")

    # ToolResult
    tr = ToolResult(call_id="call_123", name="add", output='{"sum": 3}', is_error=False)
    print(f"\n[ToolResult]")
    print(f"  call_id: {tr.call_id}")
    print(f"  name: {tr.name}")
    print(f"  output: {tr.output}")
    print(f"  is_error: {tr.is_error}")
    print(f"  to_message(): {tr.to_message()}")

    # ToolSchema
    ts = ToolSchema(
        name="add",
        description="Add two numbers",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "int"}, "b": {"type": "int"}},
        },
    )
    print(f"\n[ToolSchema]")
    print(f"  name: {ts.name}")
    print(f"  description: {ts.description}")
    print(f"  parameters: {ts.parameters}")
    print(f"  to_openai_format(): {ts.to_openai_format()}")

    # TokenUsage
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    print(f"\n[TokenUsage]")
    print(f"  prompt_tokens: {usage.prompt_tokens}")
    print(f"  completion_tokens: {usage.completion_tokens}")
    print(f"  total_tokens: {usage.total_tokens}")

    return {
        "message": msg,
        "tool_call": tc,
        "tool_result": tr,
        "tool_schema": ts,
        "token_usage": usage,
    }


# =============================================================================
# STEP 7: Demo - Full Multi-Turn Conversation
# =============================================================================


async def demo_full_conversation():
    """Run a full multi-turn conversation with the kernel."""
    print("\n" + "=" * 60)
    print("DEMO 5: Full Multi-Turn Conversation")
    print("=" * 60)

    tools = build_demo_tools()

    model_name = "hosted_vllm/Qwen/Qwen3-4B-Instruct-2507-FP8"
    client = build_client(
        {
            "base_url": "http://remora-server:8000/v1",
            "api_key": "EMPTY",
            "model": model_name,
        }
    )

    constraint = DecodingConstraint(
        strategy="structural_tag", allow_parallel_calls=True
    )
    pipeline = ConstraintPipeline(constraint)

    kernel = AgentKernel(
        client=client,
        model=model_name,
        response_parser=DefaultResponseParser(),
        constraint_pipeline=pipeline,
        tools=tools,
        observer=DemoObserver(),
        max_tokens=1024,
    )

    # Multi-turn conversation
    messages = [
        Message(
            role="system", content="You are a helpful assistant. Use tools when needed."
        ),
        Message(role="user", content="Add 5 and 3, then multiply the result by 2."),
    ]

    tool_schemas = [t.schema for t in tools]

    print("\n[Running multi-turn conversation...]")
    result = await kernel.run(messages, tool_schemas, max_turns=5)

    print("\n[Final Results]")
    print(f"  Turns: {result.turn_count}")
    print(f"  Termination: {result.termination_reason}")
    print(f"  Final content: {result.final_message.content}")

    # Print conversation history
    print("\n[Conversation History]")
    for i, msg in enumerate(result.history):
        role = msg.role
        content = msg.content or ""
        if msg.tool_calls:
            content += f" [tool_calls: {len(msg.tool_calls)}]"
        print(f"  {i + 1}. {role}: {content[:60]}...")

    await kernel.close()

    return result


# =============================================================================
# STEP 8: Demo - Provider Routing (v0.4 feature)
# =============================================================================


def demo_provider_routing():
    """Demonstrate the v0.4 provider routing."""
    print("\n" + "=" * 60)
    print("DEMO 6: Provider Routing (v0.4)")
    print("=" * 60)

    test_cases = [
        ("hosted_vllm/Qwen/Qwen3-4B", "LiteLLM with base_url"),
        ("anthropic/claude-3-sonnet", "LiteLLM (Anthropic)"),
        ("openai/gpt-4o", "LiteLLM (OpenAI)"),
        ("gpt-4o", "OpenAICompatibleClient (backwards compat)"),
    ]

    print("\n[Provider Routing]")
    for model, expected in test_cases:
        client = build_client({"model": model, "api_key": "test"})
        client_type = type(client).__name__
        print(f"  {model} -> {client_type} ({expected})")

    return test_cases


# =============================================================================
# MAIN
# =============================================================================


async def main():
    """Run all demos."""
    print("\n" + "#" * 60)
    print("# structured-agents v0.4.0 Demo")
    print("#" * 60)

    # Run demos that don't require server
    demo_types()
    demo_grammar_pipeline()
    demo_provider_routing()
    await demo_events()

    # These require the vLLM server
    try:
        await demo_kernel_direct()
    except Exception as e:
        print(f"\n[ERROR] Kernel demo failed: {e}")

    try:
        await demo_full_conversation()
    except Exception as e:
        print(f"\n[ERROR] Full conversation demo failed: {e}")

    print("\n" + "#" * 60)
    print("# Demo Complete!")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
