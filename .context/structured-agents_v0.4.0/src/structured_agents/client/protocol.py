"""LLM client protocol definition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from structured_agents.types import TokenUsage


@dataclass
class CompletionResponse:
    """Response from an LLM completion request."""

    content: str | None
    tool_calls: list[dict[str, Any]] | None
    usage: TokenUsage | None
    finish_reason: str | None
    raw_response: dict[str, Any]


class LLMClient(Protocol):
    """Protocol for LLM API clients."""

    model: str

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
        """Make a chat completion request.

        Args:
            messages: List of message dicts.
            tools: List of tool dicts (OpenAI format).
            tool_choice: Tool choice strategy.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            extra_body: Additional request body parameters (e.g., for grammar).
            model: Optional model name override.

        Returns:
            CompletionResponse with the result.
        """
        ...

    async def close(self) -> None:
        """Close any open connections."""
        ...
