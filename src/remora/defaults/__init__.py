"""Shipped default assets — bundles, queries, and config defaults.

This package is the canonical source for default bundle definitions,
tree-sitter query files, and config defaults. All assets are locatable
via importlib.resources so they work in installed (non-editable) packages.
"""

from __future__ import annotations

import yaml
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any


def defaults_dir() -> Path:
    """Return the resolved filesystem path to the defaults package directory."""
    ref = files("remora.defaults")
    # In editable installs this is already a Path; in wheel installs we need as_file
    if isinstance(ref, Path):
        return ref
    with as_file(ref) as p:
        return Path(p)


def default_bundles_dir() -> Path:
    """Return the path to the shipped default bundles."""
    return defaults_dir() / "bundles"


def default_queries_dir() -> Path:
    """Return the path to the shipped default tree-sitter queries."""
    return defaults_dir() / "queries"


def default_config_path() -> Path:
    """Return the path to defaults.yaml."""
    return defaults_dir() / "defaults.yaml"


def load_defaults() -> dict[str, Any]:
    """Load defaults.yaml and return the parsed dict."""
    path = default_config_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


__all__ = [
    "defaults_dir",
    "default_bundles_dir",
    "default_queries_dir",
    "default_config_path",
    "load_defaults",
]
