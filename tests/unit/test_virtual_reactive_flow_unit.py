from __future__ import annotations

from pathlib import Path

import pytest
from structured_agents.types import ToolCall

from remora.core.agents.trigger import TriggerPolicy
from remora.core.model.config import Config, RuntimeConfig
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
async def test_review_agent_review_diff_handles_missing_node() -> None:
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
        {"node_id": "nonexistent"},
        ToolCall(id="call-review-diff-missing-node", name="review_diff", arguments={}),
    )
    assert result.is_error is False
    assert "not found" in result.output.lower()


@pytest.mark.asyncio
async def test_companion_aggregate_digest_handles_malformed_kv() -> None:
    kv_state: dict[str, object] = {
        "project/activity_log": "legacy",
        "project/tag_frequency": [],
        "project/agent_activity": "legacy",
        "project/insights": {"legacy": "value"},
    }

    async def kv_get(key: str) -> object:
        return kv_state.get(key)

    async def kv_set(key: str, value: object) -> None:
        kv_state[key] = value

    async def my_correlation_id() -> str:
        return "corr-companion-unit"

    tool = await _discover_single_tool(
        Path("src/remora/defaults/bundles/companion/tools/aggregate_digest.pym"),
        capabilities={
            "kv_get": kv_get,
            "kv_set": kv_set,
            "my_correlation_id": my_correlation_id,
        },
    )
    result = await tool.execute(
        {
            "agent_id": "src/app.py::a",
            "summary": "summary",
            "tags": "bug, test",
            "insight": "needs follow-up",
        },
        ToolCall(id="call-aggregate-digest-unit", name="aggregate_digest", arguments={}),
    )
    assert result.is_error is False
    assert "Recorded activity for src/app.py::a" in result.output
    assert isinstance(kv_state["project/activity_log"], list)
    assert isinstance(kv_state["project/tag_frequency"], dict)
    assert isinstance(kv_state["project/agent_activity"], dict)


def test_self_trigger_loop_guard_caps_correlation_retries() -> None:
    config = Config(
        runtime=RuntimeConfig(
            trigger_cooldown_ms=0,
            max_trigger_depth=50,
            max_reactive_turns_per_correlation=3,
        )
    )
    policy = TriggerPolicy(config)

    assert policy.should_trigger("corr-loop")
    policy.release_depth("corr-loop")
    assert policy.should_trigger("corr-loop")
    policy.release_depth("corr-loop")
    assert policy.should_trigger("corr-loop")
    policy.release_depth("corr-loop")
    assert not policy.should_trigger("corr-loop")
