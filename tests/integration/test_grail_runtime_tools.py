from __future__ import annotations

from pathlib import Path

import pytest
from structured_agents.types import ToolCall

from remora.core.tools.grail import discover_tools


class _WorkspaceStub:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    async def list_dir(self, path: str = ".") -> list[str]:
        prefix = f"{path.rstrip('/')}/"
        names: list[str] = []
        for full_path in self._files:
            if full_path.startswith(prefix):
                suffix = full_path[len(prefix) :]
                if "/" not in suffix:
                    names.append(suffix)
        return sorted(names)

    async def read(self, path: str) -> str:
        return self._files[path]


def _load_fixture_tools() -> dict[str, str]:
    base = Path("tests/fixtures/grail_runtime_tools")
    files: dict[str, str] = {}
    for tool_path in sorted(base.glob("*.pym")):
        files[f"_bundle/tools/{tool_path.name}"] = tool_path.read_text(encoding="utf-8")
    return files


def _load_bundle_tools(tool_paths: list[Path]) -> dict[str, str]:
    files: dict[str, str] = {}
    for tool_path in tool_paths:
        files[f"_bundle/tools/{tool_path.name}"] = tool_path.read_text(encoding="utf-8")
    return files


@pytest.mark.asyncio
async def test_fixture_tools_execute_via_grail_runtime() -> None:
    sent_payloads: list[tuple[str, str]] = []

    async def send_message(to_node_id: str, content: str) -> dict[str, object]:
        sent_payloads.append((to_node_id, content))
        return {"sent": True, "reason": "sent"}

    async def graph_get_children(parent_id: str | None = None) -> list[dict]:
        del parent_id
        return [{"node_id": "src/a.py"}, {"node_id": "src/b.py"}]

    workspace = _WorkspaceStub(_load_fixture_tools())
    tools = await discover_tools(
        workspace,
        capabilities={
            "send_message": send_message,
            "graph_get_children": graph_get_children,
        },
    )
    by_name = {tool.schema.name: tool for tool in tools}
    assert {"echo_text", "send_prefixed_message", "count_children"} <= set(by_name)

    echo_result = await by_name["echo_text"].execute(
        {"text": "  hello  "},
        ToolCall(id="call-echo", name="echo_text", arguments={}),
    )
    send_result = await by_name["send_prefixed_message"].execute(
        {"to_node_id": "src/api", "content": "ping"},
        ToolCall(id="call-send", name="send_prefixed_message", arguments={}),
    )
    child_result = await by_name["count_children"].execute(
        {},
        ToolCall(id="call-count", name="count_children", arguments={}),
    )

    assert echo_result.is_error is False
    assert echo_result.output == "hello"
    assert send_result.is_error is False
    assert send_result.output == "sent:src/api"
    assert child_result.is_error is False
    assert child_result.output == "children:2"
    assert sent_payloads == [("src/api", "[runtime] ping")]


@pytest.mark.asyncio
async def test_bundle_tools_execute_via_grail_runtime() -> None:
    async def send_message(to_node_id: str, content: str) -> dict[str, object]:
        if to_node_id and content:
            return {"sent": True, "reason": "sent"}
        return {"sent": False, "reason": "rate_limited"}

    async def graph_get_children(parent_id: str | None = None) -> list[dict]:
        del parent_id
        return [
            {"node_type": "directory", "name": "src/api", "node_id": "src/api"},
            {"node_type": "file", "name": "orders.py", "node_id": "src/api/orders.py"},
        ]

    async def my_node_id() -> str:
        return "src/api"

    async def graph_get_node(target_id: str) -> dict | None:
        if target_id == "src/api":
            return {"parent_id": "src", "name": "api"}
        if target_id == "src":
            return {"parent_id": ".", "name": "src"}
        return None

    tool_files = _load_bundle_tools(
        [
            Path("src/remora/defaults/bundles/system/tools/send_message.pym"),
            Path("src/remora/defaults/bundles/directory-agent/tools/list_children.pym"),
            Path("src/remora/defaults/bundles/directory-agent/tools/get_parent.pym"),
        ]
    )
    workspace = _WorkspaceStub(tool_files)
    tools = await discover_tools(
        workspace,
        capabilities={
            "send_message": send_message,
            "graph_get_children": graph_get_children,
            "my_node_id": my_node_id,
            "graph_get_node": graph_get_node,
        },
    )
    by_name = {tool.schema.name: tool for tool in tools}
    assert {"send_message", "list_children", "get_parent"} <= set(by_name)

    send_result = await by_name["send_message"].execute(
        {"to_node_id": "src/models", "content": "hello"},
        ToolCall(id="call-send", name="send_message", arguments={}),
    )
    list_result = await by_name["list_children"].execute(
        {},
        ToolCall(id="call-list", name="list_children", arguments={}),
    )
    parent_result = await by_name["get_parent"].execute(
        {},
        ToolCall(id="call-parent", name="get_parent", arguments={}),
    )

    assert send_result.is_error is False
    assert "Message sent to src/models" in send_result.output
    assert list_result.is_error is False
    assert "Children:" in list_result.output
    assert "[directory] src/api" in list_result.output
    assert parent_result.is_error is False
    assert "Parent: src (src)" in parent_result.output
