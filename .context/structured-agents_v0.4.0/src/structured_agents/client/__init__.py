"""Client package for LLM connections."""

from typing import Any

from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.client.openai import OpenAICompatibleClient
from structured_agents.client.litellm_client import LiteLLMClient


def build_client(config: dict[str, Any]) -> LLMClient:
    """Build an LLM client from config dict.

    The client type is determined by the model string:
    - If model starts with a provider prefix (e.g., "hosted_vllm/", "anthropic/"),
      uses LiteLLMClient for multi-provider routing.
    - Otherwise, uses OpenAICompatibleClient for direct vLLM access.

    Config keys:
        model: Model name/path (required)
        base_url: API base URL (for vLLM endpoints)
        api_key: API key (defaults to "EMPTY" for local vLLM)
        timeout: Request timeout in seconds (default 120.0)
    """
    model = config.get("model", "default")
    base_url = config.get("base_url", "http://localhost:8000/v1")
    api_key = config.get("api_key", "EMPTY")
    timeout = config.get("timeout", 120.0)

    # Use LiteLLM if model has a provider prefix
    known_prefixes = (
        "hosted_vllm/",
        "anthropic/",
        "openai/",
        "gemini/",
        "azure/",
        "bedrock/",
        "vertex_ai/",
    )

    if any(model.startswith(prefix) for prefix in known_prefixes):
        return LiteLLMClient(
            model=model,
            api_key=api_key if api_key != "EMPTY" else None,
            base_url=base_url if "hosted_vllm" in model else None,
            timeout=timeout,
        )

    # Default to OpenAI-compatible client for backwards compatibility
    return OpenAICompatibleClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
    )


__all__ = [
    "CompletionResponse",
    "LLMClient",
    "OpenAICompatibleClient",
    "LiteLLMClient",
    "build_client",
]
