"""Tests for companion KV tools."""

from __future__ import annotations

from pathlib import Path

TOOLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "remora"
    / "defaults"
    / "bundles"
    / "system"
    / "tools"
)


def test_companion_summarize_exists() -> None:
    tool_path = TOOLS_DIR / "companion_summarize.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text(encoding="utf-8")
    assert "companion/chat_index" in content
    assert "kv_set" in content
    assert "kv_get" in content


def test_companion_reflect_exists() -> None:
    tool_path = TOOLS_DIR / "companion_reflect.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text(encoding="utf-8")
    assert "companion/reflections" in content
    assert "kv_set" in content


def test_companion_link_exists() -> None:
    tool_path = TOOLS_DIR / "companion_link.pym"
    assert tool_path.exists(), f"Missing tool: {tool_path}"
    content = tool_path.read_text(encoding="utf-8")
    assert "companion/links" in content
    assert "target_node_id" in content


def test_companion_bundle_exists() -> None:
    bundle_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "remora"
        / "defaults"
        / "bundles"
        / "companion"
        / "bundle.yaml"
    )
    assert bundle_path.exists()
    import yaml

    config = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert config["name"] == "companion"
    assert "turn_digested" in config.get("system_prompt", "")


def test_aggregate_digest_tool_exists() -> None:
    tool_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "remora"
        / "defaults"
        / "bundles"
        / "companion"
        / "tools"
        / "aggregate_digest.pym"
    )
    assert tool_path.exists()
    content = tool_path.read_text(encoding="utf-8")
    assert "project/activity_log" in content
    assert "project/tag_frequency" in content
    assert "kv_set" in content
