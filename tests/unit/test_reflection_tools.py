from __future__ import annotations

from pathlib import Path

import grail


def test_reflection_tools_parse_from_system_bundle() -> None:
    tools_dir = Path("src/remora/defaults/bundles/system/tools")
    expected = {"reflect", "categorize", "find_links", "summarize"}

    for name in expected:
        tool_file = tools_dir / f"{name}.pym"
        assert tool_file.is_file()
        script = grail.load(tool_file)
        assert script.name == name


def test_companion_bundle_removed() -> None:
    bundle_dir = Path("src/remora/defaults/bundles/companion")
    assert bundle_dir.exists()
    assert (bundle_dir / "bundle.yaml").exists()
    assert (bundle_dir / "tools" / "aggregate_digest.pym").exists()
