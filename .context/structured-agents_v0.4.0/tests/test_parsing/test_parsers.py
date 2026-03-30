"""Tests for response parsing."""

import pytest
from structured_agents.parsing import (
    ResponseParser,
    DefaultResponseParser,
    get_response_parser,
)
from structured_agents.types import ToolCall


class TestDefaultResponseParser:
    """Tests for DefaultResponseParser."""

    def test_parse_plain_content(self):
        """Plain text content should pass through unchanged."""
        parser = DefaultResponseParser()
        content, tool_calls = parser.parse("Hello, world!", None)
        assert content == "Hello, world!"
        assert tool_calls == []

    def test_parse_with_tool_calls(self):
        """OpenAI-style tool calls should be parsed correctly."""
        parser = DefaultResponseParser()
        raw_tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "add_numbers",
                    "arguments": '{"x": 1, "y": 2}',
                },
            }
        ]
        content, tool_calls = parser.parse(None, raw_tool_calls)

        assert content is None
        assert len(tool_calls) == 1
        assert tool_calls[0].id == "call_123"
        assert tool_calls[0].name == "add_numbers"
        assert tool_calls[0].arguments == {"x": 1, "y": 2}

    def test_parse_xml_tool_calls_in_content(self):
        """XML-style tool calls in content should be parsed."""
        parser = DefaultResponseParser()
        content = '<tool_call>{"name": "get_weather", "arguments": {"city": "NYC"}}</tool_call>'

        result_content, tool_calls = parser.parse(content, None)

        assert result_content is None
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "get_weather"
        assert tool_calls[0].arguments == {"city": "NYC"}

    def test_parse_multiple_xml_tool_calls(self):
        """Multiple XML tool calls should all be parsed."""
        parser = DefaultResponseParser()
        content = """
        <tool_call>{"name": "tool1", "arguments": {"a": 1}}</tool_call>
        <tool_call>{"name": "tool2", "arguments": {"b": 2}}</tool_call>
        """

        result_content, tool_calls = parser.parse(content, None)

        assert len(tool_calls) == 2
        assert tool_calls[0].name == "tool1"
        assert tool_calls[1].name == "tool2"

    def test_parse_malformed_json_in_tool_call(self):
        """Malformed JSON in tool calls should not crash."""
        parser = DefaultResponseParser()
        raw_tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "broken",
                    "arguments": "not valid json",
                },
            }
        ]
        content, tool_calls = parser.parse(None, raw_tool_calls)

        assert len(tool_calls) == 1
        assert tool_calls[0].arguments == {}  # Falls back to empty dict


class TestGetResponseParser:
    """Tests for get_response_parser factory."""

    def test_returns_default_parser_for_unknown_model(self):
        """Unknown model names should return DefaultResponseParser."""
        parser = get_response_parser("unknown-model")
        assert isinstance(parser, DefaultResponseParser)

    def test_returns_default_parser_for_qwen(self):
        """'qwen' should return DefaultResponseParser."""
        parser = get_response_parser("qwen")
        assert isinstance(parser, DefaultResponseParser)

    def test_strips_provider_prefix(self):
        """Provider prefixes should be stripped when looking up parser."""
        parser = get_response_parser("hosted_vllm/Qwen/Qwen3-4B")
        assert isinstance(parser, DefaultResponseParser)

    def test_handles_anthropic_prefix(self):
        """anthropic/ prefix should be handled."""
        parser = get_response_parser("anthropic/claude-3-opus")
        assert isinstance(parser, DefaultResponseParser)
