from __future__ import annotations

from pathlib import Path

import grail
import yaml


def test_directory_tools_parse() -> None:
    tools_dir = Path("src/remora/defaults/bundles/directory-agent/tools")
    tool_files = sorted(tools_dir.glob("*.pym"))
    assert tool_files
    expected = {"list_children", "get_parent"}
    names = {tool_file.stem for tool_file in tool_files}
    assert expected.issubset(names)
    for tool_file in tool_files:
        script = grail.load(tool_file)
        assert script.name == tool_file.stem


def test_directory_bundle_yaml_valid() -> None:
    bundle_path = Path("src/remora/defaults/bundles/directory-agent/bundle.yaml")
    data = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "system_prompt" not in data
    assert data.get("system_prompt_extension")
    assert data.get("prompts", {}).get("chat")
    assert data.get("prompts", {}).get("reactive")
