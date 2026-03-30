"""LiteLLM client for multi-provider LLM access."""

from __future__ import annotations
from typing import Any

import litellm
from structured_agents.client.protocol import CompletionResponse
from structured_agents.types import TokenUsage


class LiteLLMClient:
    """LLM client using LiteLLM for multi-provider routing.

    Model string prefixes determine the provider:
    - "hosted_vllm/..." → vLLM endpoint
    - "anthropic/..." → Anthropic
    - "openai/..." → OpenAI
    - etc.

    See https://docs.litellm.ai/docs/providers for full list.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        """Initialize LiteLLM client.

        Args:
            model: Model string with provider prefix (e.g. "hosted_vllm/Qwen/Qwen3-4B")
            api_key: API key for the provider (optional, uses env vars if not set)
            base_url: Base URL for self-hosted endpoints (required for hosted_vllm)
            timeout: Request timeout in seconds
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

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
        """Make a chat completion request via LiteLLM.

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
        model_to_use = model or self.model

        kwargs: dict[str, Any] = {
            "model": model_to_use,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self.timeout,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        if self.base_url:
            kwargs["api_base"] = self.base_url

        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        if extra_body is not None:
            kwargs["extra_body"] = extra_body

        response = await litellm.acompletion(**kwargs)

        if not response.choices:
            return CompletionResponse(
                content="",
                tool_calls=None,
                usage=None,
                finish_reason="empty",
                raw_response=response.model_dump()
                if hasattr(response, "model_dump")
                else {},
            )

        choice = response.choices[0]
        message = choice.message

        content = message.content
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]

        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason,
            raw_response=response.model_dump()
            if hasattr(response, "model_dump")
            else {},
        )

    async def close(self) -> None:
        """Close any open connections (no-op for LiteLLM)."""
        pass
