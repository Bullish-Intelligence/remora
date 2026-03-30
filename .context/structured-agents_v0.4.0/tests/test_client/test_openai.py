# tests/test_client/test_openai.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from structured_agents.client.openai import OpenAICompatibleClient


@pytest.mark.asyncio
async def test_openai_client_chat_completion():
    client = OpenAICompatibleClient(
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="test-model",
    )

    with patch.object(client, "_client") as mock_client:
        mock_response = MagicMock(
            id="chatcmpl-123",
            choices=[
                MagicMock(
                    message=MagicMock(content="Hello", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="test-model",
        )
        mock_response.to_dict.return_value = {}

        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await client.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            tools=None,
        )

        assert result.content == "Hello"
