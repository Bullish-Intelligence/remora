"""AgentKernel - the core agent loop orchestrator."""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.events.types import (
    Event,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.exceptions import KernelError
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.parsing.parsers import ResponseParser, DefaultResponseParser
from structured_agents.tools.protocol import Tool
from structured_agents.types import (
    Message,
    RunResult,
    StepResult,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSchema,
)


# Provider prefixes that support grammar constraints (via extra_body)
_GRAMMAR_SUPPORTED_PREFIXES = ("hosted_vllm/",)


def _supports_grammar_constraints(model: str) -> bool:
    """Check if a model supports grammar constraints via extra_body."""
    return any(model.startswith(prefix) for prefix in _GRAMMAR_SUPPORTED_PREFIXES)


@dataclass
class AgentKernel:
    """The core agent loop orchestrator.

    The kernel runs a step loop: call LLM -> parse response -> execute tools -> repeat.

    Args:
        client: LLM client for making completion requests
        response_parser: Parser for extracting tool calls from model output
        tools: Sequence of tools available to the agent
        observer: Event observer for lifecycle events
        constraint_pipeline: Optional grammar constraint pipeline (vLLM only)
        max_history_messages: Maximum messages to keep in history
        max_concurrency: Maximum concurrent tool executions
        max_tokens: Maximum tokens per completion
        temperature: Sampling temperature
        tool_choice: Tool choice strategy
    """

    client: LLMClient
    response_parser: ResponseParser = field(default_factory=DefaultResponseParser)
    tools: Sequence[Tool] = field(default_factory=list)
    observer: Observer = field(default_factory=NullObserver)
    constraint_pipeline: ConstraintPipeline | None = None
    max_history_messages: int = 50
    max_concurrency: int = 1
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"

    def __post_init__(self) -> None:
        self._tool_map: dict[str, Tool] = {t.schema.name: t for t in self.tools}

    async def step(
        self,
        messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        turn: int = 0,
    ) -> StepResult:
        """Execute a single turn: model call + tool execution."""
        resolved_tools: list[ToolSchema] = []
        for t in tools:
            if isinstance(t, ToolSchema):
                resolved_tools.append(t)
            elif isinstance(t, str):
                tool = self._tool_map.get(t)
                if tool:
                    resolved_tools.append(tool.schema)

        # Format messages and tools for API
        formatted_messages = [msg.to_openai_format() for msg in messages]
        formatted_tools = (
            [ts.to_openai_format() for ts in resolved_tools] if resolved_tools else None
        )

        # Apply grammar constraints only for supported providers
        extra_body = None
        if self.constraint_pipeline and _supports_grammar_constraints(
            self.client.model
        ):
            extra_body = self.constraint_pipeline.constrain(resolved_tools)

        request_start = time.perf_counter()
        try:
            await self.observer.emit(
                ModelRequestEvent(
                    turn=turn,
                    messages_count=len(formatted_messages),
                    tools_count=len(resolved_tools),
                    model=self.client.model,
                )
            )

            response = await self.client.chat_completion(
                messages=formatted_messages,
                tools=formatted_tools,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                extra_body=extra_body,
            )
        except Exception as e:
            raise KernelError(f"API call failed: {e}", turn=turn, phase="model_request")

        request_duration_ms = int((time.perf_counter() - request_start) * 1000)

        await self.observer.emit(
            ModelResponseEvent(
                turn=turn,
                duration_ms=request_duration_ms,
                content=response.content,
                tool_calls_count=len(response.tool_calls) if response.tool_calls else 0,
                usage=response.usage,
            )
        )

        content, tool_calls = self.response_parser.parse(
            response.content, response.tool_calls
        )

        response_message = Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )

        tool_results = []
        errors_count = 0

        async def execute_one(tc: ToolCall) -> ToolResult:
            nonlocal errors_count
            await self.observer.emit(
                ToolCallEvent(
                    turn=turn,
                    tool_name=tc.name,
                    call_id=tc.id,
                    arguments=tc.arguments,
                )
            )
            tool_start = time.perf_counter()
            tool = self._tool_map.get(tc.name)
            if not tool:
                result = ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=f"Unknown tool: {tc.name}",
                    is_error=True,
                )
                errors_count += 1
                return result
            try:
                result = await tool.execute(tc.arguments, tc)
            except Exception as e:
                result = ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=str(e),
                    is_error=True,
                )
                errors_count += 1

            duration_ms = int((time.perf_counter() - tool_start) * 1000)
            await self.observer.emit(
                ToolResultEvent(
                    turn=turn,
                    tool_name=tc.name,
                    call_id=tc.id,
                    is_error=result.is_error,
                    duration_ms=duration_ms,
                    output_preview=result.output[:100] if result.output else "",
                )
            )
            return result

        if tool_calls:
            if self.max_concurrency <= 1:
                tool_results = [await execute_one(tc) for tc in tool_calls]
            else:
                sem = asyncio.Semaphore(self.max_concurrency)

                async def bounded(tc: ToolCall) -> ToolResult:
                    async with sem:
                        return await execute_one(tc)

                tool_results = list(
                    await asyncio.gather(*[bounded(tc) for tc in tool_calls])
                )

        await self.observer.emit(
            TurnCompleteEvent(
                turn=turn,
                tool_calls_count=len(tool_calls) if tool_calls else 0,
                tool_results_count=len(tool_results),
                errors_count=errors_count,
            )
        )

        return StepResult(
            response_message=response_message,
            tool_calls=list(tool_calls) if tool_calls else [],
            tool_results=tool_results,
            usage=response.usage,
        )

    async def run(
        self,
        initial_messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        max_turns: int = 20,
    ) -> RunResult:
        """Execute the full agent loop."""
        messages = list(initial_messages)
        turn_count = 0
        termination_reason = "max_turns"

        run_start = time.perf_counter()

        await self.observer.emit(
            KernelStartEvent(
                max_turns=max_turns,
                tools_count=len(self.tools),
                initial_messages_count=len(initial_messages),
            )
        )

        while turn_count < max_turns:
            turn_count += 1

            if len(messages) > self.max_history_messages:
                messages = [messages[0]] + messages[-(self.max_history_messages - 1) :]

            step_result = await self.step(messages, tools, turn=turn_count)

            messages.append(step_result.response_message)
            for result in step_result.tool_results:
                messages.append(result.to_message())

            if not step_result.tool_calls:
                termination_reason = "no_tool_calls"
                break

        run_duration_ms = int((time.perf_counter() - run_start) * 1000)

        await self.observer.emit(
            KernelEndEvent(
                turn_count=turn_count,
                termination_reason=termination_reason,
                total_duration_ms=run_duration_ms,
            )
        )

        final_message = (
            messages[-1] if messages else Message(role="assistant", content="")
        )

        return RunResult(
            final_message=final_message,
            history=messages,
            turn_count=turn_count,
            termination_reason=termination_reason,
        )

    async def close(self) -> None:
        await self.client.close()
