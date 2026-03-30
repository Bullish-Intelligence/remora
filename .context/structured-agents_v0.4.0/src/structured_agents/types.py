"""Core data types for structured-agents."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


# =============================================================================
# Messages
# =============================================================================


@dataclass(frozen=True, slots=True)
class Message:
    """A conversation message in the agent loop."""

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI API message format."""
        msg: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments_json,
                    },
                }
                for tc in self.tool_calls
            ]

        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id

        if self.name:
            msg["name"] = self.name

        return msg


# =============================================================================
# Tool Calls and Results
# =============================================================================


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A parsed tool call from model output."""

    id: str
    name: str
    arguments: dict[str, Any]

    @property
    def arguments_json(self) -> str:
        """Arguments as JSON string."""
        return json.dumps(self.arguments)

    @classmethod
    def create(cls, name: str, arguments: dict[str, Any]) -> "ToolCall":
        """Create a ToolCall with auto-generated ID."""
        return cls(
            id=f"call_{uuid.uuid4().hex[:12]}",
            name=name,
            arguments=arguments,
        )


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result of executing a tool."""

    call_id: str
    name: str
    output: str
    is_error: bool = False

    def to_message(self) -> Message:
        """Convert to a tool response message."""
        return Message(
            role="tool",
            content=self.output,
            tool_call_id=self.call_id,
            name=self.name,
        )


# =============================================================================
# Tool Schemas
# =============================================================================


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """Schema for a tool, in OpenAI function format."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI tools array format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# =============================================================================
# Token Usage
# =============================================================================


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token usage statistics from a completion."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# =============================================================================
# Results
# =============================================================================


@dataclass(frozen=True, slots=True)
class StepResult:
    """Result of a single kernel step (one model call + tool execution)."""

    response_message: Message
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    """Result of a full kernel run (multiple turns until termination)."""

    final_message: Message
    history: list[Message]
    turn_count: int
    termination_reason: str
    final_tool_result: ToolResult | None = None
    total_usage: TokenUsage | None = None
