"""Response parser implementations."""

from __future__ import annotations
import json
import re
from typing import Any, Protocol
from structured_agents.types import ToolCall


class ResponseParser(Protocol):
    """Parses model responses to extract tool calls."""

    def parse(
        self, content: str | None, tool_calls: list[dict[str, Any]] | None
    ) -> tuple[str | None, list[ToolCall]]: ...


class DefaultResponseParser:
    """Default parser for tool-calling models.

    Handles:
    - OpenAI-style tool_calls from the API response
    - XML-style <tool_call> tags in content (fallback)
    """

    def parse(
        self, content: str | None, tool_calls: list[dict[str, Any]] | None
    ) -> tuple[str | None, list[ToolCall]]:
        if tool_calls:
            parsed = []
            for tc in tool_calls:
                if isinstance(tc, dict) and "function" in tc:
                    func = tc["function"]
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    parsed.append(
                        ToolCall(id=tc["id"], name=func["name"], arguments=args)
                    )
            return None, parsed

        if content:
            parsed_xml_calls = self._parse_xml_tool_calls(content)
            if parsed_xml_calls:
                return None, parsed_xml_calls

        return content, []

    def _parse_xml_tool_calls(self, content: str) -> list[ToolCall]:
        """Parse XML-style tool calls from content."""
        pattern = r"<tool_call>(.*?)</tool_call>"

        tool_calls = []
        matches = re.findall(pattern, content, re.DOTALL)

        for match in matches:
            inner = match.strip()
            try:
                data = json.loads(inner)
                name = data.get("name", "")
                args = data.get("arguments", {})
                if name:
                    tool_calls.append(ToolCall.create(name, args))
            except json.JSONDecodeError:
                pass

        return tool_calls


# Registry for model-specific parsers
_PARSER_REGISTRY: dict[str, type[ResponseParser]] = {
    "qwen": DefaultResponseParser,
    "function_gemma": DefaultResponseParser,
}


def get_response_parser(model_name: str) -> ResponseParser:
    """Look up the response parser for a model family.

    Args:
        model_name: Model family name (e.g., "qwen", "function_gemma")

    Returns:
        A ResponseParser instance for the model family.
        Defaults to DefaultResponseParser if no specific parser is registered.
    """
    # Strip provider prefix if present (e.g., "hosted_vllm/Qwen/..." -> "Qwen/...")
    if "/" in model_name:
        parts = model_name.split("/")
        # Check for known provider prefixes
        known_prefixes = {
            "hosted_vllm",
            "anthropic",
            "openai",
            "gemini",
            "azure",
            "bedrock",
            "vertex_ai",
        }
        if parts[0] in known_prefixes:
            model_name = "/".join(parts[1:])

    # Try exact match first
    parser_cls = _PARSER_REGISTRY.get(model_name)

    # Try lowercase
    if parser_cls is None:
        parser_cls = _PARSER_REGISTRY.get(model_name.lower())

    # Default to DefaultResponseParser
    if parser_cls is None:
        parser_cls = DefaultResponseParser

    return parser_cls()
