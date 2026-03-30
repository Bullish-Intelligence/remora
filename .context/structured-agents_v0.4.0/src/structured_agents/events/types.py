"""Event types for unified event model - Pydantic models."""

from __future__ import annotations
from typing import Any, Union

from pydantic import BaseModel, ConfigDict
from structured_agents.types import TokenUsage


class KernelEvent(BaseModel):
    """Base class for all kernel events.

    All kernel events are frozen (immutable) Pydantic models that can be
    serialized to JSON for event streaming and logging.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class KernelStartEvent(KernelEvent):
    """Emitted when kernel.run() begins."""

    max_turns: int
    tools_count: int
    initial_messages_count: int


class KernelEndEvent(KernelEvent):
    """Emitted when kernel.run() completes."""

    turn_count: int
    termination_reason: str
    total_duration_ms: int


class ModelRequestEvent(KernelEvent):
    """Emitted before each LLM API call."""

    turn: int
    messages_count: int
    tools_count: int
    model: str


class ModelResponseEvent(KernelEvent):
    """Emitted after each LLM API response."""

    turn: int
    duration_ms: int
    content: str | None
    tool_calls_count: int
    usage: TokenUsage | None


class ToolCallEvent(KernelEvent):
    """Emitted before each tool execution."""

    turn: int
    tool_name: str
    call_id: str
    arguments: dict[str, Any]


class ToolResultEvent(KernelEvent):
    """Emitted after each tool execution."""

    turn: int
    tool_name: str
    call_id: str
    is_error: bool
    duration_ms: int
    output_preview: str


class TurnCompleteEvent(KernelEvent):
    """Emitted after each turn (model call + all tool executions)."""

    turn: int
    tool_calls_count: int
    tool_results_count: int
    errors_count: int


Event = Union[
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
]
