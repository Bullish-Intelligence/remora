"""File change detection via watchfiles."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from remora.code.paths import resolve_discovery_paths, walk_source_files
from remora.core.model.config import Config


class FileWatcher:
    """Detects source-file changes for incremental reconciliation."""

    def __init__(self, config: Config, project_root: Path) -> None:
        self._config = config
        self._project_root = project_root.resolve()
        self._running = False
        self._stop_task: asyncio.Task | None = None

    @property
    def stop_task(self) -> asyncio.Task | None:
        """Expose the current stop-event task for shutdown coordination."""
        return self._stop_task

    def collect_file_mtimes(self) -> dict[str, int]:
        """Scan discovery paths and return `{absolute_file_path: mtime_ns}`."""
        mtimes: dict[str, int] = {}
        discovery_paths = resolve_discovery_paths(self._config, self._project_root)
        for file_path in walk_source_files(
            discovery_paths, self._config.project.workspace_ignore_patterns
        ):
            try:
                mtimes[str(file_path)] = file_path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
        return mtimes

    async def watch(self, on_changes: Callable[[set[str]], Awaitable[None]]) -> None:
        """Watch for filesystem changes and invoke `on_changes` per batch."""
        import watchfiles

        self._running = True
        paths_to_watch = resolve_discovery_paths(self._config, self._project_root)
        watch_paths = [str(path) for path in paths_to_watch if path.exists()]
        if not watch_paths:
            raise RuntimeError(
                "No discovery paths exist to watch. "
                "Create configured discovery paths before starting reconciler."
            )

        try:
            async for changes in watchfiles.awatch(*watch_paths, stop_event=self._stop_event()):
                if not self._running:
                    break
                changed_files = {str(Path(path)) for _change_type, path in changes}
                await on_changes(changed_files)
        finally:
            self._running = False

    def stop(self) -> None:
        """Request watch loop shutdown."""
        self._running = False
        if self._stop_task is not None and not self._stop_task.done():
            self._stop_task.cancel()

    def _stop_event(self):  # noqa: ANN201
        """Return a threading event set when watcher stops."""
        import threading

        if self._stop_task is not None and not self._stop_task.done():
            self._stop_task.cancel()

        event = threading.Event()

        async def _checker() -> None:
            try:
                while self._running:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass
            finally:
                event.set()

        self._stop_task = asyncio.create_task(_checker())
        return event


__all__ = ["FileWatcher"]
