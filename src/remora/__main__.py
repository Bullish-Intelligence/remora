"""Remora CLI entry point (Typer-based)."""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Annotated

import typer

from remora.code.discovery import discover as discover_nodes
from remora.code.languages import LanguageRegistry
from remora.code.paths import resolve_discovery_paths, resolve_query_paths
from remora.core.model.config import load_config
from remora.core.model.node import Node
from remora.core.services.lifecycle import RemoraLifecycle

app = typer.Typer(
    name="remora",
    help="Remora - event-driven graph agent runner.",
    no_args_is_help=True,
    add_completion=False,
)


class _StructuredFieldInjector(logging.Filter):
    """Inject default structured context fields for non-actor log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "node_id"):
            record.node_id = "-"
        if not hasattr(record, "correlation_id"):
            record.correlation_id = "-"
        if not hasattr(record, "turn"):
            record.turn = "-"
        return True


PROJECT_ROOT_ARG = typer.Option(
    "--project-root",
    exists=True,
    file_okay=False,
    dir_okay=True,
)
CONFIG_ARG = typer.Option("--config")
PORT_ARG = typer.Option("--port", min=1, max=65535)
BIND_ARG = typer.Option(
    "--bind",
    help="Address to bind the web server to (use 0.0.0.0 for all interfaces).",
)
NO_WEB_ARG = typer.Option("--no-web")
RUN_SECONDS_ARG = typer.Option(
    "--run-seconds",
    help="Run for N seconds then shut down (useful for smoke tests).",
)
LOG_LEVEL_ARG = typer.Option(
    "--log-level",
    help="Python logging level (DEBUG, INFO, WARNING, ERROR).",
)
LOG_EVENTS_ARG = typer.Option(
    "--log-events/--no-log-events",
    help="Emit one runtime log line for each persisted event.",
)
LSP_ARG = typer.Option(
    "--lsp",
    help="Start the optional LSP server on stdin/stdout after runtime services are ready.",
)


@app.command("start")
def start_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    port: Annotated[int, PORT_ARG] = 8080,
    bind: Annotated[str, BIND_ARG] = "127.0.0.1",
    no_web: Annotated[bool, NO_WEB_ARG] = False,
    run_seconds: Annotated[float, RUN_SECONDS_ARG] = 0.0,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
    log_events: Annotated[bool, LOG_EVENTS_ARG] = False,
    lsp: Annotated[bool, LSP_ARG] = False,
) -> None:
    """Start Remora components and run until interrupted."""
    _configure_logging(log_level, lsp_mode=lsp)
    try:
        asyncio.run(
            _start(
                project_root=project_root,
                config_path=config_path,
                port=port,
                bind=bind,
                no_web=no_web,
                run_seconds=run_seconds,
                log_events=log_events,
                lsp=lsp,
            )
        )
    except KeyboardInterrupt:
        pass


@app.command("discover")
def discover_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
) -> None:
    """Run discovery and print a node summary."""
    nodes = asyncio.run(_discover(project_root=project_root, config_path=config_path))
    typer.echo(f"Discovered {len(nodes)} nodes")
    for node in nodes:
        typer.echo(f"{node.node_type:8} {node.file_path}::{node.full_name}")


@app.command("index")
def index_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    collection: Annotated[str | None, typer.Option("--collection", "-c")] = None,
    include: Annotated[list[str] | None, typer.Option("--include", "-i")] = None,
    exclude: Annotated[list[str] | None, typer.Option("--exclude", "-e")] = None,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
) -> None:
    """Index project files for semantic search via embeddy."""
    _configure_logging(log_level)
    try:
        asyncio.run(
            _index(
                project_root=project_root,
                config_path=config_path,
                collection=collection,
                include=include,
                exclude=exclude,
            )
        )
    except KeyboardInterrupt:
        pass


@app.command("lsp")
def lsp_command(
    project_root: Annotated[Path, PROJECT_ROOT_ARG] = Path("."),
    config_path: Annotated[Path | None, CONFIG_ARG] = None,
    log_level: Annotated[str, LOG_LEVEL_ARG] = "INFO",
) -> None:
    """Start the LSP server standalone using a shared Remora sqlite database."""
    _configure_logging(log_level, lsp_mode=True)
    logger = logging.getLogger(__name__)

    project_root = project_root.resolve()
    config = load_config(config_path)
    db_path = project_root / config.infra.workspace_root / "remora.db"
    if not db_path.exists():
        logger.error("Database not found at %s. Is 'remora start' running?", db_path)
        raise typer.Exit(code=1)

    try:
        from remora.lsp import create_lsp_server_standalone

        lsp_server = create_lsp_server_standalone(db_path)
    except ImportError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    logger.info("Starting standalone LSP server on stdin/stdout")
    lsp_server.start_io()


async def _start(
    *,
    project_root: Path,
    config_path: Path | None,
    port: int,
    no_web: bool,
    bind: str = "127.0.0.1",
    run_seconds: float = 0.0,
    log_events: bool = False,
    lsp: bool = False,
) -> None:
    project_root = project_root.resolve()
    config = load_config(config_path)
    lifecycle = RemoraLifecycle(
        config=config,
        project_root=project_root,
        bind=bind,
        port=port,
        no_web=no_web,
        log_events=log_events,
        lsp=lsp,
        configure_file_logging=_configure_file_logging,
    )
    try:
        await lifecycle.start()
        await lifecycle.run(run_seconds=run_seconds)
    finally:
        await lifecycle.shutdown()


async def _discover(
    *,
    project_root: Path,
    config_path: Path | None,
) -> list[Node]:
    project_root = project_root.resolve()
    config = load_config(config_path)
    discovery_paths = resolve_discovery_paths(config, project_root)
    query_paths = resolve_query_paths(config, project_root)

    language_registry = LanguageRegistry.from_config(
        language_defs=config.behavior.languages,
        query_search_paths=query_paths,
    )

    return discover_nodes(
        discovery_paths,
        language_map=config.behavior.language_map,
        language_registry=language_registry,
        query_paths=query_paths,
        languages=list(config.project.discovery_languages)
        if config.project.discovery_languages
        else None,
        ignore_patterns=config.project.workspace_ignore_patterns,
    )


async def _index(
    *,
    project_root: Path,
    config_path: Path | None,
    collection: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
) -> None:
    project_root = project_root.resolve()
    config = load_config(config_path)

    if not config.search.enabled:
        typer.echo("Error: search is not enabled in remora.yaml", err=True)
        typer.echo("Add 'search: { enabled: true }' to your config.", err=True)
        raise typer.Exit(code=1)

    from remora.core.services.search import SearchService

    service = SearchService(config.search, project_root)
    await service.initialize()
    if not service.available:
        await service.close()
        typer.echo("Error: search service is not available.", err=True)
        typer.echo("Check that embeddy is installed and the server is running.", err=True)
        raise typer.Exit(code=1)

    paths = resolve_discovery_paths(config, project_root)
    total_stats = {"files_processed": 0, "chunks_created": 0, "errors": []}

    try:
        for path in paths:
            if not path.exists():
                typer.echo(f"Skipping non-existent path: {path}")
                continue
            typer.echo(f"Indexing {path}...")
            stats = await service.index_directory(
                str(path),
                collection=collection,
                include=include,
                exclude=exclude,
            )
            files = int(stats.get("files_processed", 0))
            chunks = int(stats.get("chunks_created", 0))
            errors = list(stats.get("errors", []))
            total_stats["files_processed"] += files
            total_stats["chunks_created"] += chunks
            total_stats["errors"].extend(errors)
            typer.echo(f"  {files} files -> {chunks} chunks")
            for error in errors:
                typer.echo(f"  Error: {error}", err=True)
    finally:
        await service.close()

    typer.echo(
        f"\nDone: {total_stats['files_processed']} files, "
        f"{total_stats['chunks_created']} chunks, "
        f"{len(total_stats['errors'])} errors"
    )


def main() -> None:
    """CLI entrypoint used by `python -m remora` and script wrappers."""
    app(prog_name="remora")


def _configure_logging(level_name: str, *, lsp_mode: bool = False) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise typer.BadParameter(f"Invalid log level: {level_name}")
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if root_logger.handlers:
        return

    stream = sys.stderr if lsp_mode else sys.stdout
    stream_handler = logging.StreamHandler(stream)
    stream_handler.addFilter(_StructuredFieldInjector())
    log_format = (
        "%(asctime)s %(levelname)s %(name)s [%(node_id)s:%(turn)s %(correlation_id)s]: %(message)s"
    )
    stream_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(stream_handler)


def _configure_file_logging(log_path: Path) -> None:
    root_logger = logging.getLogger()
    resolved_path = log_path.resolve()
    existing_handler_for_path = False
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.FileHandler):
            try:
                handler_path = Path(handler.baseFilename).resolve()
            except OSError:
                handler_path = None
            if handler_path == resolved_path:
                existing_handler_for_path = True
                continue
            root_logger.removeHandler(handler)
            handler.close()

    if existing_handler_for_path:
        return

    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.addFilter(_StructuredFieldInjector())
    file_handler.setLevel(root_logger.level)
    log_format = (
        "%(asctime)s %(levelname)s %(name)s [%(node_id)s:%(turn)s %(correlation_id)s]: %(message)s"
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(file_handler)


if __name__ == "__main__":
    main()
