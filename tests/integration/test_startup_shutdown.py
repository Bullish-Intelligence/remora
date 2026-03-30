from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.factories import write_file

from remora.__main__ import _start


@pytest.mark.asyncio
async def test_startup_shutdown_path_runs_cleanly_for_two_seconds(tmp_path: Path) -> None:
    write_file(tmp_path / "src" / "app.py", "def a():\n    return 1\n")
    config_path = tmp_path / "remora.yaml"
    config_path.write_text(
        (
            "discovery_paths:\n"
            "  - src\n"
            "discovery_languages:\n"
            "  - python\n"
            "language_map:\n"
            "  .py: python\n"
            "query_search_paths:\n"
            "  - \"@default\"\n"
            "workspace_root: .remora-startup-shutdown\n"
        ),
        encoding="utf-8",
    )

    await _start(
        project_root=tmp_path,
        config_path=config_path,
        port=8089,
        no_web=True,
        bind="127.0.0.1",
        run_seconds=2.0,
        log_events=False,
        lsp=False,
    )

    db_path = tmp_path / ".remora-startup-shutdown" / "remora.db"
    log_path = tmp_path / ".remora-startup-shutdown" / "remora.log"
    assert db_path.exists()
    assert log_path.exists()

    pending_remora_tasks = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and task.get_name().startswith("remora-")
    ]
    assert pending_remora_tasks == []
