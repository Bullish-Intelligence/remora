from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from remora.code.directories import DirectoryManager
from remora.core.model.config import BehaviorConfig, Config, InfraConfig, ProjectConfig


def _config() -> Config:
    return Config(
        project=ProjectConfig(
            discovery_paths=("src",),
            discovery_languages=("python",),
        ),
        behavior=BehaviorConfig(
            language_map={".py": "python"},
            query_search_paths=("@default",),
            bundle_search_paths=("bundles",),
        ),
        infra=InfraConfig(workspace_root=".remora-reconcile"),
    )


def test_directory_manager_computes_parent_hierarchy(tmp_path: Path) -> None:
    manager = DirectoryManager(
        _config(),
        node_store=AsyncMock(),
        event_store=AsyncMock(),
        workspace_service=AsyncMock(),
        project_root=tmp_path,
        remove_node=AsyncMock(),
        register_subscriptions=AsyncMock(),
        provision_bundle=AsyncMock(),
    )

    first = tmp_path / "src" / "pkg" / "mod.py"
    second = tmp_path / "src" / "root.py"
    dir_paths, children_by_dir = manager.compute_hierarchy({str(first), str(second)})

    assert "." in dir_paths
    assert "src" in dir_paths
    assert "src/pkg" in dir_paths
    assert "src" in children_by_dir["."]
    assert "src/root.py" in children_by_dir["src"]
    assert "src/pkg/mod.py" in children_by_dir["src/pkg"]
