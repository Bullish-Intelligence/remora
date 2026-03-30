"""Bundle configuration validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from remora.core.tools.context import EXTERNALS_VERSION


def test_code_agent_bundle_has_self_reflect() -> None:
    bundle_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "remora"
        / "defaults"
        / "bundles"
        / "code-agent"
        / "bundle.yaml"
    )
    config = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert "self_reflect" in config
    self_reflect = config["self_reflect"]
    assert self_reflect["enabled"] is True
    assert "model" in self_reflect
    assert "prompt" in self_reflect
    assert self_reflect["max_turns"] >= 1


@pytest.mark.parametrize("bundle_name", ["review-agent", "companion"])
def test_virtual_bundle_externals_version_is_supported(bundle_name: str) -> None:
    bundle_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "remora"
        / "defaults"
        / "bundles"
        / bundle_name
        / "bundle.yaml"
    )
    config = yaml.safe_load(bundle_path.read_text(encoding="utf-8"))
    assert config["externals_version"] <= EXTERNALS_VERSION
