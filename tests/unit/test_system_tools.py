from __future__ import annotations

from pathlib import Path

import grail
import yaml


def test_system_tools_parse() -> None:
    tools_dir = Path("src/remora/defaults/bundles/system/tools")
    tool_files = sorted(tools_dir.glob("*.pym"))
    assert tool_files
    expected = {"send_message", "broadcast", "query_agents", "subscribe", "unsubscribe"}
    expected |= {"kv_get", "kv_set"}
    expected |= {"reflect", "categorize", "find_links", "summarize"}
    names = {tool_file.stem for tool_file in tool_files}
    assert expected.issubset(names)
    for tool_file in tool_files:
        script = grail.load(tool_file)
        assert script.name == tool_file.stem


def test_system_bundle_yaml_valid() -> None:
    bundle_path = Path("src/remora/defaults/bundles/system/bundle.yaml")
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "system_prompt" in data
    assert "model" in data
    assert "max_turns" in data
    assert data.get("prompts", {}).get("chat")
    assert data.get("prompts", {}).get("reactive")
