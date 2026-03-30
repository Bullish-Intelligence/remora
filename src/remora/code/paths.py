"""Centralized path resolution and source file walking."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from remora.core.model.config import Config, resolve_query_search_paths


def resolve_discovery_paths(config: Config, project_root: Path) -> list[Path]:
    """Resolve configured discovery paths relative to project root."""
    resolved: list[Path] = []
    for configured in config.project.discovery_paths:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        resolved_candidate = candidate.resolve()
        if resolved_candidate.exists():
            resolved.append(resolved_candidate)
    return resolved


def resolve_query_paths(config: Config, project_root: Path) -> list[Path]:
    """Resolve configured query search paths relative to project root."""
    return resolve_query_search_paths(config, project_root)


def walk_source_files(
    paths: list[Path],
    ignore_patterns: tuple[str, ...] = (),
) -> list[Path]:
    """Collect source files from paths while respecting ignore patterns."""
    discovered: list[Path] = []
    seen: set[Path] = set()
    normalized = tuple(pattern.strip() for pattern in ignore_patterns if pattern.strip())

    def ignored(path: Path) -> bool:
        text = path.as_posix()
        parts = set(path.parts)
        for pattern in normalized:
            if pattern in parts:
                return True
            if fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True
            if fnmatch.fnmatch(text, f"*/{pattern}/*"):
                return True
        return False

    for raw in paths:
        root = raw.resolve()
        if not root.exists():
            continue
        if root.is_file():
            if root not in seen and not ignored(root):
                seen.add(root)
                discovered.append(root)
            continue
        for candidate in root.rglob("*"):
            if not candidate.is_file() or ignored(candidate) or candidate in seen:
                continue
            seen.add(candidate)
            discovered.append(candidate)

    return sorted(discovered)


__all__ = ["resolve_discovery_paths", "resolve_query_paths", "walk_source_files"]
