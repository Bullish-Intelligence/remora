from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.core.model.config import Config
from remora.core.services.lifecycle import RemoraLifecycle


@pytest.mark.asyncio
async def test_run_indefinite_logs_task_exceptions_instead_of_raising(caplog) -> None:
    async def ok_task() -> str:
        return "ok"

    async def failing_task() -> None:
        raise RuntimeError("boom")

    lifecycle = RemoraLifecycle(
        config=Config(),
        project_root=Path("."),
        bind="127.0.0.1",
        port=8080,
        no_web=True,
        log_events=False,
        lsp=False,
        configure_file_logging=lambda _path: None,
    )
    lifecycle._started = True  # noqa: SLF001
    lifecycle._tasks = [
        asyncio.create_task(ok_task(), name="ok-task"),
        asyncio.create_task(failing_task(), name="failing-task"),
    ]

    await lifecycle.run(run_seconds=0)

    assert "Runtime task failing-task exited with exception: boom" in caplog.text
