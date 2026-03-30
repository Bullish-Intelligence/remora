"""Tests for client factory helpers."""

from structured_agents.client import (
    OpenAICompatibleClient,
    LiteLLMClient,
    build_client,
)


def test_build_client_returns_openai_client_for_plain_model() -> None:
    """Plain model names should use OpenAICompatibleClient for backwards compat."""
    config = {"base_url": "http://localhost:8000/v1", "model": "test"}
    client = build_client(config)
    assert isinstance(client, OpenAICompatibleClient)


def test_build_client_returns_litellm_for_hosted_vllm() -> None:
    """hosted_vllm/ prefix should use LiteLLMClient."""
    config = {
        "base_url": "http://localhost:8000/v1",
        "model": "hosted_vllm/Qwen/Qwen3-4B",
        "api_key": "test-key",
    }
    client = build_client(config)
    assert isinstance(client, LiteLLMClient)
    assert client.model == "hosted_vllm/Qwen/Qwen3-4B"
    assert client.base_url == "http://localhost:8000/v1"


def test_build_client_returns_litellm_for_anthropic() -> None:
    """anthropic/ prefix should use LiteLLMClient."""
    config = {
        "model": "anthropic/claude-3-opus-20240229",
        "api_key": "sk-ant-...",
    }
    client = build_client(config)
    assert isinstance(client, LiteLLMClient)
    assert client.model == "anthropic/claude-3-opus-20240229"
    # base_url should be None for cloud providers
    assert client.base_url is None


def test_build_client_returns_litellm_for_openai() -> None:
    """openai/ prefix should use LiteLLMClient."""
    config = {
        "model": "openai/gpt-4-turbo",
        "api_key": "sk-...",
    }
    client = build_client(config)
    assert isinstance(client, LiteLLMClient)
    assert client.model == "openai/gpt-4-turbo"
