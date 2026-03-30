from __future__ import annotations

from pathlib import Path

import pytest
from structured_agents.types import ToolCall

from remora.core.tools.grail import GrailTool, discover_tools


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


def _tool_workspace(tool_path: Path) -> _WorkspaceStub:
    return _WorkspaceStub(
        {
            f"_bundle/tools/{tool_path.name}": tool_path.read_text(encoding="utf-8"),
        }
    )


async def _discover_single_tool(
    tool_path: Path,
    *,
    capabilities: dict[str, object],
) -> GrailTool:
    workspace = _tool_workspace(tool_path)
    tools = await discover_tools(workspace, capabilities=capabilities)
    assert len(tools) == 1
    return tools[0]


@pytest.mark.asyncio
async def test_review_diff_handles_missing_node_without_error() -> None:
    async def graph_get_node(_target_id: str) -> dict | None:
        return None

    async def kv_get(_key: str) -> str | None:
        return None

    async def kv_set(_key: str, _value: str) -> None:
        return None

    tool = await _discover_single_tool(
        Path("src/remora/defaults/bundles/review-agent/tools/review_diff.pym"),
        capabilities={
            "graph_get_node": graph_get_node,
            "kv_get": kv_get,
            "kv_set": kv_set,
        },
    )
    result = await tool.execute(
        {"node_id": "src/missing.py::fn"},
        ToolCall(id="call-review-diff-missing", name="review_diff", arguments={}),
    )

    assert result.is_error is False
    assert "not found" in result.output.lower()


@pytest.mark.asyncio
async def test_list_recent_changes_bounds_large_output() -> None:
    async def graph_query_nodes(
        node_type: str | None = None,
        status: str | None = None,
        file_path: str | None = None,
        role: str | None = None,
    ) -> list[dict]:
        del node_type, status, file_path, role
        return [
            {
                "node_type": "function",
                "full_name": f"src/api/very_long_module_name_{idx}/" + ("x" * 160),
                "node_id": f"node-{idx}",
            }
            for idx in range(80)
        ]

    tool = await _discover_single_tool(
        Path("src/remora/defaults/bundles/review-agent/tools/list_recent_changes.pym"),
        capabilities={"graph_query_nodes": graph_query_nodes},
    )
    result = await tool.execute(
        {},
        ToolCall(id="call-list-recent", name="list_recent_changes", arguments={}),
    )

    assert result.is_error is False
    assert result.output.startswith("Nodes (80 total")
    assert len(result.output) <= 2000


@pytest.mark.asyncio
async def test_submit_review_handles_unexpected_send_message_shape() -> None:
    async def send_message(_to_agent: str, _content: str) -> object:
        return "unexpected-string"

    tool = await _discover_single_tool(
        Path("src/remora/defaults/bundles/review-agent/tools/submit_review.pym"),
        capabilities={"send_message": send_message},
    )
    result = await tool.execute(
        {
            "node_id": "src/models/order.py::OrderRequest",
            "finding": "Tax rate validation should reject negative values.",
            "severity": "high",
            "notify_user": False,
        },
        ToolCall(id="call-submit-review-shape", name="submit_review", arguments={}),
    )

    assert result.is_error is False
    assert "Unexpected response from send_message" in result.output


@pytest.mark.asyncio
async def test_submit_review_rejects_empty_node_id_without_sending() -> None:
    sent: list[tuple[str, str]] = []

    async def send_message(to_agent: str, content: str) -> dict[str, object]:
        sent.append((to_agent, content))
        return {"sent": True, "reason": "sent"}

    tool = await _discover_single_tool(
        Path("src/remora/defaults/bundles/review-agent/tools/submit_review.pym"),
        capabilities={"send_message": send_message},
    )
    result = await tool.execute(
        {
            "node_id": "   ",
            "finding": "Avoid duplicated edge registration.",
            "severity": "info",
            "notify_user": False,
        },
        ToolCall(id="call-submit-review-empty-node", name="submit_review", arguments={}),
    )

    assert result.is_error is False
    assert "non-empty" in result.output.lower()
    assert sent == []


@pytest.mark.asyncio
async def test_aggregate_digest_recovers_from_malformed_kv_state() -> None:
    kv_state: dict[str, object] = {
        "project/activity_log": "legacy-string-instead-of-list",
        "project/tag_frequency": "legacy-string-instead-of-dict",
        "project/agent_activity": ["legacy-list-instead-of-dict"],
        "project/insights": {"legacy": "dict-instead-of-list"},
    }

    async def kv_get(key: str) -> object:
        return kv_state.get(key)

    async def kv_set(key: str, value: object) -> None:
        kv_state[key] = value

    async def my_correlation_id() -> str:
        return "corr-real-world-1"

    tool = await _discover_single_tool(
        Path("src/remora/defaults/bundles/companion/tools/aggregate_digest.pym"),
        capabilities={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )

    long_summary = "summary-" + ("x" * 1000)
    long_insight = "insight-" + ("y" * 500)
    result = await tool.execute(
        {
            "agent_id": "src/api/orders.py::create_order",
            "summary": long_summary,
            "tags": "bug, performance, architecture",
            "insight": long_insight,
        },
        ToolCall(id="call-aggregate-digest", name="aggregate_digest", arguments={}),
    )

    assert result.is_error is False
    assert "Recorded activity for src/api/orders.py::create_order" in result.output

    activity_log = kv_state["project/activity_log"]
    assert isinstance(activity_log, list)
    latest_activity = activity_log[-1]
    assert len(latest_activity["summary"]) <= 500
    assert latest_activity["correlation_id"] == "corr-real-world-1"

    tag_frequency = kv_state["project/tag_frequency"]
    assert isinstance(tag_frequency, dict)
    assert tag_frequency["bug"] >= 1

    agent_activity = kv_state["project/agent_activity"]
    assert isinstance(agent_activity, dict)

    insights = kv_state["project/insights"]
    assert isinstance(insights, list)
    latest_insight = insights[-1]
    assert len(latest_insight["insight"]) <= 200
