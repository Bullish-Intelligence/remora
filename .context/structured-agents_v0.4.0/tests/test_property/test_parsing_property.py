"""Property-based tests for response parsing using Hypothesis."""

from __future__ import annotations

import json
import re
from typing import Any

from hypothesis import given, strategies as st, assume, settings

from structured_agents.parsing.parsers import DefaultResponseParser
from structured_agents.types import Message, ToolCall


# =============================================================================
# Custom Strategies
# =============================================================================

tool_names = st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True)

json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=50).filter(lambda s: "<" not in s and ">" not in s),
)

json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=15).filter(lambda s: s.isidentifier()),
    json_primitives,
    max_size=5,
)


def make_xml_tool_call(name: str, args: dict[str, Any]) -> str:
    """Create XML tool call string."""
    args_json = json.dumps(args)
    return f'<tool_call>{{"name": "{name}", "arguments": {args_json}}}</tool_call>'


# =============================================================================
# DefaultResponseParser Property Tests
# =============================================================================


class TestDefaultResponseParserProperties:
    """Property tests for DefaultResponseParser."""

    @given(content=st.text(max_size=500).filter(lambda s: "<tool_call>" not in s))
    def test_plain_content_preserved(self, content: str):
        """Plain content without tool calls should be preserved."""
        parser = DefaultResponseParser()

        # Parser takes content and tool_calls as separate args
        parsed_content, tool_calls = parser.parse(content, None)

        assert parsed_content == content
        assert tool_calls == []

    @given(name=tool_names, args=json_dicts)
    def test_single_xml_tool_call_parsed(self, name: str, args: dict[str, Any]):
        """Single XML tool call should be parsed correctly."""
        xml_call = make_xml_tool_call(name, args)
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(xml_call, None)

        assert len(tool_calls) == 1
        assert tool_calls[0].name == name
        assert tool_calls[0].arguments == args

    @given(
        prefix=st.text(max_size=100).filter(lambda s: "<tool_call>" not in s),
        name=tool_names,
        args=json_dicts,
        suffix=st.text(max_size=100).filter(lambda s: "<tool_call>" not in s),
    )
    def test_xml_tool_call_with_surrounding_text(
        self, prefix: str, name: str, args: dict[str, Any], suffix: str
    ):
        """XML tool calls should be extracted even with surrounding text."""
        xml_call = make_xml_tool_call(name, args)
        content = f"{prefix}{xml_call}{suffix}"
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(content, None)

        # Tool call should be extracted
        assert len(tool_calls) == 1
        assert tool_calls[0].name == name

    @given(
        name1=tool_names,
        args1=json_dicts,
        name2=tool_names,
        args2=json_dicts,
    )
    def test_multiple_xml_tool_calls(
        self,
        name1: str,
        args1: dict[str, Any],
        name2: str,
        args2: dict[str, Any],
    ):
        """Multiple XML tool calls should all be parsed."""
        xml1 = make_xml_tool_call(name1, args1)
        xml2 = make_xml_tool_call(name2, args2)
        content = f"{xml1}\n{xml2}"
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(content, None)

        assert len(tool_calls) == 2
        names = {tc.name for tc in tool_calls}
        assert name1 in names
        assert name2 in names

    @given(content=st.text(max_size=200))
    def test_native_tool_calls_take_precedence(self, content: str):
        """Native tool_calls should be used over XML parsing."""
        native_tc = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "native_tool",
                    "arguments": '{"key": "value"}',
                },
            }
        ]
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(content, native_tc)

        # Should return native tool calls, not parse XML
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "native_tool"
        assert tool_calls[0].id == "call_123"

    @given(
        names=st.lists(tool_names, min_size=1, max_size=5, unique=True),
        args_list=st.lists(json_dicts, min_size=1, max_size=5),
    )
    def test_multiple_native_tool_calls_preserved(
        self, names: list[str], args_list: list[dict[str, Any]]
    ):
        """Multiple native tool calls should all be preserved."""
        # Zip to match names with args
        pairs = list(zip(names, args_list[: len(names)]))
        native_calls = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args),
                },
            }
            for i, (name, args) in enumerate(pairs)
        ]

        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse("", native_calls)

        assert len(tool_calls) == len(native_calls)
        for i, parsed in enumerate(tool_calls):
            assert parsed.id == f"call_{i}"

    def test_empty_content_handled(self):
        """Empty content should return empty results."""
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse("", None)

        assert parsed_content == ""
        assert tool_calls == []

    def test_none_content_handled(self):
        """None content should be handled gracefully."""
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(None, None)

        assert parsed_content is None
        assert tool_calls == []

    @given(name=tool_names)
    def test_malformed_json_in_tool_call_handled(self, name: str):
        """Malformed JSON in tool_call should not crash."""
        # Create malformed XML tool call
        content = f'<tool_call>{{"name": "{name}", "arguments": {{not valid json}}}}</tool_call>'
        parser = DefaultResponseParser()

        # Should not raise, but may not extract the tool call
        parsed_content, tool_calls = parser.parse(content, None)

        # The malformed call might be skipped or kept as content
        # Key invariant: no exception raised
        assert isinstance(parsed_content, str) or parsed_content is None

    @given(
        tool_name=tool_names,
        args=json_dicts,
    )
    def test_tool_call_ids_are_unique(self, tool_name: str, args: dict[str, Any]):
        """Generated tool call IDs should be unique."""
        xml_call = make_xml_tool_call(tool_name, args)
        content = f"{xml_call}\n{xml_call}"  # Same call twice
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(content, None)

        if len(tool_calls) >= 2:
            ids = [tc.id for tc in tool_calls]
            assert len(ids) == len(set(ids)), "Tool call IDs should be unique"


# =============================================================================
# Edge Cases
# =============================================================================


class TestParserEdgeCases:
    """Test edge cases in parsing."""

    def test_nested_angle_brackets_handled(self):
        """Nested angle brackets in content should not break parser."""
        content = "Here is some <code>example</code> text without tool calls"
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(content, None)

        # Should not extract false positives
        assert tool_calls == []
        assert parsed_content == content

    def test_partial_tool_call_tag_handled(self):
        """Partial tool_call tags should not crash."""
        content = "<tool_call>incomplete..."
        parser = DefaultResponseParser()

        parsed_content, tool_calls = parser.parse(content, None)

        # Should handle gracefully
        assert isinstance(parsed_content, str)
