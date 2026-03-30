"""OpenAI-compatible LLM client."""

from __future__ import annotations
from typing import Any
from openai import AsyncOpenAI
from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.types import TokenUsage


class OpenAICompatibleClient:
    """OpenAI-compatible client for vLLM and similar backends."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "EMPTY",
        model: str = "default",
        timeout: float = 120.0,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )

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
        """Make a chat completion request."""
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools is not None:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if extra_body is not None:
            kwargs["extra_body"] = extra_body

        response = await self._client.chat.completions.create(**kwargs)

        if not response.choices:
            return CompletionResponse(
                content="",
                tool_calls=None,
                usage=None,
                finish_reason="empty",
                raw_response=response.model_dump(),
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
            raw_response=response.model_dump(),
        )

    async def close(self) -> None:
        await self._client.close()


def build_client(config: dict[str, Any]) -> OpenAICompatibleClient:
    """Build an LLM client from config dict."""
    return OpenAICompatibleClient(
        base_url=config.get("base_url", "http://localhost:8000/v1"),
        api_key=config.get("api_key", "EMPTY"),
        model=config.get("model", "default"),
        timeout=config.get("timeout", 120.0),
    )
