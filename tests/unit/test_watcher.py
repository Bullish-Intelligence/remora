from __future__ import annotations

from pathlib import Path

from tests.factories import write_file

from remora.code.watcher import FileWatcher
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


def test_file_watcher_collect_file_mtimes(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    write_file(source, "def a():\n    return 1\n")

    watcher = FileWatcher(_config(), tmp_path)
    mtimes = watcher.collect_file_mtimes()

    assert str(source) in mtimes
    assert mtimes[str(source)] > 0
