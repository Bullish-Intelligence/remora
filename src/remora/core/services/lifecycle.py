"""Runtime lifecycle orchestration for Remora services."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uvicorn

from remora.core.model.config import Config
from remora.core.storage.db import open_database

if TYPE_CHECKING:
    from remora.core.events import Event
    from remora.core.services.container import RuntimeServices

logger = logging.getLogger(__name__)


class RemoraLifecycle:
    """Own startup, run loop, and ordered shutdown for runtime services.

    Note on Task Management Strategy:

    This class uses manual asyncio.Task management (self._tasks list) rather
    than asyncio.TaskGroup for several critical reasons:

    1. **Graceful Shutdown Required**: Each service type needs specific shutdown
       logic that cannot be handled by simple task cancellation:
       - ActorPool: Must call stop_and_wait() with timeout to drain in-flight work
       - FileReconciler: Has a separate stop_task that must complete
       - Uvicorn server: Requires should_exit flag to be set, then task must finish
       - LSP server: Must follow LSP protocol (shutdown() then exit() sequence)

    2. **Ordered Shutdown**: Services must shut down in a specific order:
       - First: Stop accepting new work (reconciler.stop(), runner.stop())
       - Second: Signal web server to exit
       - Third: Close services (database connections, etc.)
       - Fourth: LSP shutdown (if applicable)
       - Finally: Wait for tasks to complete, then force-cancel stragglers

    3. **Timeout Handling**: The shutdown sequence has a 10-second timeout for
       graceful shutdown, after which tasks are forcibly cancelled. This prevents
       hung services from blocking runtime shutdown indefinitely.

    4. **Resource Cleanup**: File log handlers must be released to avoid FD leaks
       across restarts. This requires explicit tracking and cleanup in finally block.

    5. **LSP Protocol Compliance**: The LSP server requires a specific shutdown
       sequence (shutdown() followed by exit()) that cannot be expressed with
       TaskGroup's simple cancellation model.

    Using TaskGroup would require wrapping all this logic anyway, defeating the
    purpose. Manual task management, while more verbose, provides the explicit
    control needed for production-grade graceful shutdown.

    See: .scratch/projects/44-code-review-4/PHASE_4_5_IMPLEMENTATION_REVIEW.md
    """

    def __init__(
        self,
        *,
        config: Config,
        project_root: Path,
        bind: str,
        port: int,
        no_web: bool,
        log_events: bool,
        lsp: bool,
        configure_file_logging: Callable[[Path], None],
    ) -> None:
        self._config = config
        self._project_root = project_root.resolve()
        self._bind = bind
        self._port = port
        self._no_web = no_web
        self._log_events = log_events
        self._lsp = lsp
        self._configure_file_logging = configure_file_logging

        self._services: RuntimeServices | None = None
        self._tasks: list[asyncio.Task] = []
        self._web_server: uvicorn.Server | None = None
        self._web_task: asyncio.Task | None = None
        self._lsp_server: Any | None = None
        self._started = False
        self._log_path: Path | None = None

    async def start(self) -> None:
        """Initialize services and launch background runtime tasks.

        This method performs a full initialization sequence:
        1. Configure logging to file
        2. Open database connection
        3. Initialize RuntimeServices (container for all services)
        4. Perform initial discovery scan (full file system scan)
        5. Launch background tasks (runner, reconciler, web server, LSP)

        After this method completes, the runtime is fully operational and
        ready to handle requests.

        Raises:
            RuntimeError: If RuntimeServices fails to initialize reconciler or runner.
        """
        from remora.core.services.container import RuntimeServices

        db_path = self._project_root / self._config.infra.workspace_root / "remora.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        log_path = db_path.parent / "remora.log"
        self._log_path = log_path.resolve()
        self._configure_file_logging(log_path)

        db = await open_database(db_path)
        services = RuntimeServices(self._config, self._project_root, db)
        self._services = services

        logger.info("Logging to %s", log_path)
        logger.info("Initializing runtime services")
        await services.initialize()
        if services.reconciler is None:
            raise RuntimeError("RuntimeServices.initialize() did not set reconciler")
        if services.runner is None:
            raise RuntimeError("RuntimeServices.initialize() did not set runner")

        if self._log_events:
            event_logger = logging.getLogger("remora.events")

            def log_event(event: Event) -> None:
                event_logger.info(
                    "event=%s corr=%s agent=%s from=%s to=%s path=%s",
                    event.event_type,
                    event.correlation_id or "-",
                    getattr(event, "agent_id", "-"),
                    getattr(event, "from_agent", "-"),
                    getattr(event, "to_agent", "-"),
                    getattr(event, "path", None) or getattr(event, "file_path", "-"),
                )

            services.event_bus.subscribe_all(log_event)
            logger.info("Event activity logging enabled")

        logger.info("Starting full discovery scan")
        scan_started = time.perf_counter()
        scanned_nodes = await services.reconciler.full_scan()
        logger.info(
            "Discovery complete: nodes=%d duration=%.2fs",
            len(scanned_nodes),
            time.perf_counter() - scan_started,
        )

        runner_task = asyncio.create_task(services.runner.run_forever(), name="remora-runner")
        reconciler_task = asyncio.create_task(
            services.reconciler.run_forever(),
            name="remora-reconciler",
        )
        self._tasks = [runner_task, reconciler_task]

        if not self._no_web:
            from remora.web.server import create_app

            web_app = create_app(
                services.event_store,
                services.node_store,
                services.event_bus,
                human_input_broker=services.human_input_broker,
                metrics=services.metrics,
                actor_pool=services.runner,
                workspace_service=services.workspace_service,
                search_service=services.search_service,
                chat_message_max_chars=self._config.runtime.chat_message_max_chars,
                conversation_history_max_entries=self._config.runtime.conversation_history_max_entries,
                conversation_message_max_chars=self._config.runtime.conversation_message_max_chars,
            )
            logger.info("Starting web server on %s:%d", self._bind, self._port)
            web_config = uvicorn.Config(
                web_app,
                host=self._bind,
                port=self._port,
                log_level="warning",
                access_log=False,
            )
            self._web_server = uvicorn.Server(web_config)
            self._web_task = asyncio.create_task(self._web_server.serve(), name="remora-web")
            self._tasks.append(self._web_task)
        else:
            logger.info("Web server disabled (--no-web)")

        if self._lsp:
            from remora.lsp import create_lsp_server

            self._lsp_server = create_lsp_server(
                services.node_store,
                services.event_store,
                web_port=self._port,
            )
            logger.info("Starting LSP server on stdin/stdout")
            lsp_task = asyncio.create_task(
                asyncio.to_thread(self._lsp_server.start_io),
                name="remora-lsp",
            )
            self._tasks.append(lsp_task)

        self._started = True

    async def run(self, *, run_seconds: float = 0.0) -> None:
        """Run the lifecycle until timeout or until one task exits unexpectedly.

        Args:
            run_seconds: If > 0, run for this many seconds then shut down.
                        If 0, run indefinitely until all tasks complete.

        Note:
            This method does NOT use asyncio.TaskGroup because the lifecycle
            requires explicit control over task lifecycle for graceful shutdown.
            See the class docstring for detailed rationale.
        """
        if not self._started:
            raise RuntimeError("RemoraLifecycle.start() must be called before run()")

        if run_seconds > 0:
            await asyncio.sleep(run_seconds)
        else:
            results = await asyncio.gather(*self._tasks, return_exceptions=True)
            for index, result in enumerate(results):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.error(
                        "Runtime task %s exited with exception: %s",
                        self._tasks[index].get_name(),
                        result,
                    )

    async def shutdown(self) -> None:
        """Stop tasks and close services in a deterministic order.

        This method implements a carefully ordered shutdown sequence to ensure
        graceful termination of all services. The order is critical:

        1. Stop accepting new work (reconciler, runner)
        2. Wait for in-flight work to complete (with timeout)
        3. Signal web server to exit (should_exit flag)
        4. Close services (database connections, workspace locks)
        5. LSP shutdown (if applicable, follows LSP protocol)
        6. Wait for tasks to complete gracefully (10s timeout)
        7. Force-cancel any remaining tasks
        8. Release file log handlers (prevents FD leaks)

        Args:
            None

        Raises:
            None: All exceptions are caught and logged to avoid crashing shutdown.

        Note:
            The 10-second timeout for graceful shutdown is intentional. If a service
            cannot shut down within this time, it is forcibly cancelled to prevent
            the runtime from hanging indefinitely. This is a safety measure, not a
            bug — services should be designed to shut down quickly.
        """
        services = self._services

        try:
            if services is None:
                return

            if services.reconciler is not None:
                services.reconciler.stop()
            if services.runner is not None:
                try:
                    await asyncio.wait_for(services.runner.stop_and_wait(), timeout=10.0)
                except TimeoutError:
                    logger.warning("Actor pool did not drain within 10s, forcing shutdown")

            reconciler_stop_task = (
                services.reconciler.stop_task if services.reconciler is not None else None
            )
            if self._web_server is not None:
                self._web_server.should_exit = True

            await services.close()

            if self._lsp_server is not None:
                try:
                    await asyncio.to_thread(self._lsp_server.shutdown)
                # Error boundary: LSP shutdown failures must not block runtime shutdown.
                except OSError as exc:
                    logger.warning("LSP shutdown failed: %s", exc)
                try:
                    await asyncio.to_thread(self._lsp_server.exit)
                # Error boundary: force-exit is best-effort cleanup only.
                except OSError:
                    pass

            if reconciler_stop_task is not None and reconciler_stop_task not in self._tasks:
                self._tasks.append(reconciler_stop_task)

            # Let tasks finish cooperatively first (especially uvicorn lifespan).
            pending = [task for task in self._tasks if not task.done()]
            if pending:
                done, still_pending = await asyncio.wait(pending, timeout=10.0)
                if still_pending:
                    task_names = sorted(task.get_name() for task in still_pending)
                    logger.warning(
                        "Forcing cancellation of %d lingering tasks after graceful shutdown: %s",
                        len(still_pending),
                        ", ".join(task_names),
                    )
                    for task in still_pending:
                        task.cancel()
                    await asyncio.gather(*still_pending, return_exceptions=True)

                task_failures = [
                    task.exception()
                    for task in done
                    if not task.cancelled() and task.exception() is not None
                ]
                if task_failures:
                    logger.warning(
                        "Runtime task(s) ended with exceptions during shutdown: %s",
                        "; ".join(str(exc) for exc in task_failures),
                    )
        finally:
            self._release_file_log_handlers()
            self._started = False
            self._services = None
            self._tasks = []
            self._web_server = None
            self._web_task = None

    def _release_file_log_handlers(self) -> None:
        """Release lifecycle-owned file handlers to avoid FD leaks across starts."""
        if self._log_path is None:
            return
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if not isinstance(handler, logging.FileHandler):
                continue
            try:
                handler_path = Path(handler.baseFilename).resolve()
            except OSError:
                handler_path = None
            if handler_path != self._log_path:
                continue
            root_logger.removeHandler(handler)
            handler.close()
        self._log_path = None


__all__ = ["RemoraLifecycle"]
