# src/embeddy/cli/main.py
"""Typer CLI for embeddy.

Commands:
    embeddy serve     — Start the HTTP server
    embeddy ingest    — Ingest text, files, or directories
    embeddy search    — Search a collection
    embeddy info      — Show version and configuration
"""

from __future__ import annotations

import asyncio
import json as json_lib
import sys
from pathlib import Path
from typing import Any, Optional

import typer

import embeddy
from embeddy.config import EmbeddyConfig, EmbedderConfig, StoreConfig, ServerConfig, load_config_file
from embeddy.exceptions import EmbeddyError

try:
    import uvicorn
except ImportError:  # pragma: no cover
    uvicorn = None  # type: ignore[assignment]

app = typer.Typer(
    name="embeddy",
    help="Async-native embedding, chunking, hybrid search, and RAG pipeline.",
    no_args_is_help=True,
)

ingest_app = typer.Typer(
    name="ingest",
    help="Ingest text, files, or directories into a collection.",
    no_args_is_help=True,
)
app.add_typer(ingest_app, name="ingest")


# ---------------------------------------------------------------------------
# Config resolution helper
# ---------------------------------------------------------------------------


def _resolve_config(
    config_path: str | None = None,
    db: str | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str | None = None,
) -> EmbeddyConfig:
    """Build an EmbeddyConfig from optional file + CLI overrides."""
    if config_path:
        cfg = load_config_file(config_path)
    else:
        cfg = EmbeddyConfig()

    # Apply CLI overrides
    if db is not None:
        cfg = cfg.model_copy(update={"store": cfg.store.model_copy(update={"db_path": db})})
    if host is not None:
        cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"host": host})})
    if port is not None:
        cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"port": port})})
    if log_level is not None:
        cfg = cfg.model_copy(update={"server": cfg.server.model_copy(update={"log_level": log_level})})

    return cfg


# ---------------------------------------------------------------------------
# Dependency builder (mockable in tests)
# ---------------------------------------------------------------------------


def _build_deps(config: EmbeddyConfig) -> tuple:
    """Build the core dependencies: (embedder, store, pipeline, search_service).

    This function is the sole integration point for real objects. Tests
    patch this to inject mocks.
    """
    from embeddy.embedding import Embedder
    from embeddy.store import VectorStore
    from embeddy.pipeline import Pipeline
    from embeddy.search import SearchService

    embedder = Embedder(config.embedder)
    store = VectorStore(config.store)

    # Initialize store synchronously via asyncio.run if needed
    loop = asyncio.new_event_loop()
    loop.run_until_complete(store.initialize())
    loop.close()

    pipeline = Pipeline(
        embedder=embedder,
        store=store,
        collection=config.pipeline.collection,
        chunk_config=config.chunk,
    )
    search_service = SearchService(embedder=embedder, store=store)

    return embedder, store, pipeline, search_service


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_ingest_stats(stats: Any, as_json: bool = False) -> str:
    """Format IngestStats for display."""
    data = {
        "files_processed": stats.files_processed,
        "chunks_created": stats.chunks_created,
        "chunks_embedded": stats.chunks_embedded,
        "chunks_stored": stats.chunks_stored,
        "chunks_skipped": stats.chunks_skipped,
        "errors": [{"file_path": e.file_path, "error": e.error} for e in stats.errors],
        "elapsed_seconds": round(stats.elapsed_seconds, 3),
    }
    if as_json:
        return json_lib.dumps(data, indent=2)

    lines = [
        "Ingest complete:",
        f"  files processed : {data['files_processed']}",
        f"  chunks created  : {data['chunks_created']}",
        f"  chunks embedded : {data['chunks_embedded']}",
        f"  chunks stored   : {data['chunks_stored']}",
        f"  chunks skipped  : {data['chunks_skipped']}",
        f"  elapsed         : {data['elapsed_seconds']}s",
    ]
    if data["errors"]:
        lines.append(f"  errors          : {len(data['errors'])}")
        for err in data["errors"]:
            lines.append(f"    - {err['file_path']}: {err['error']}")
    return "\n".join(lines)


def _format_search_results(results: Any, as_json: bool = False) -> str:
    """Format SearchResults for display."""
    data = {
        "query": results.query,
        "collection": results.collection,
        "mode": results.mode.value if hasattr(results.mode, "value") else str(results.mode),
        "total_results": results.total_results,
        "elapsed_ms": round(results.elapsed_ms, 2),
        "results": [],
    }
    for r in results.results:
        entry: dict[str, Any] = {
            "chunk_id": r.chunk_id,
            "score": round(r.score, 4) if r.score is not None else None,
            "source_path": r.source_path,
            "content": r.content,
        }
        data["results"].append(entry)

    if as_json:
        return json_lib.dumps(data, indent=2)

    lines = [
        f"Search: {data['total_results']} result(s) for '{data['query']}' "
        f"(mode={data['mode']}, {data['elapsed_ms']}ms)",
        "",
    ]
    for i, r in enumerate(data["results"], 1):
        score_str = f"{r['score']:.4f}" if r["score"] is not None else "n/a"
        lines.append(f"  [{i}] score={score_str}  source={r['source_path']}")
        # Show first 200 chars of content
        content_preview = r["content"][:200]
        if len(r["content"]) > 200:
            content_preview += "..."
        lines.append(f"      {content_preview}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"embeddy {embeddy.__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Top-level app callback (for --version)
# ---------------------------------------------------------------------------


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Embeddy: async-native embedding, chunking, hybrid search, and RAG pipeline."""


# ---------------------------------------------------------------------------
# embeddy info
# ---------------------------------------------------------------------------


@app.command()
def info() -> None:
    """Show version, default configuration, and system info."""
    cfg = EmbeddyConfig()
    lines = [
        f"embeddy {embeddy.__version__}",
        "",
        "Default configuration:",
        f"  embedder.model_name      : {cfg.embedder.model_name}",
        f"  embedder.mode            : {cfg.embedder.mode}",
        f"  embedder.dimension       : {cfg.embedder.embedding_dimension}",
        f"  embedder.normalize       : {cfg.embedder.normalize}",
        f"  store.db_path            : {cfg.store.db_path}",
        f"  pipeline.collection      : {cfg.pipeline.collection}",
        f"  server.host              : {cfg.server.host}",
        f"  server.port              : {cfg.server.port}",
    ]
    typer.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# embeddy serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to config file (YAML/JSON)."),
    host: Optional[str] = typer.Option(None, "--host", "-h", help="Host to bind to."),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Port to bind to."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    log_level: Optional[str] = typer.Option(None, "--log-level", "-l", help="Log level (debug/info/warning/error)."),
) -> None:
    """Start the embeddy HTTP server."""
    if uvicorn is None:
        typer.echo("Error: uvicorn is not installed. Install with: pip install embeddy[server]", err=True)
        raise typer.Exit(code=1)

    cfg = _resolve_config(config_path=config, db=db, host=host, port=port, log_level=log_level)

    typer.echo(f"Building dependencies (model={cfg.embedder.model_name})...")
    embedder, store, pipeline, search_service = _build_deps(cfg)

    from embeddy.server import create_app

    fastapi_app = create_app(
        embedder=embedder,
        store=store,
        pipeline=pipeline,
        search_service=search_service,
    )

    typer.echo(f"Starting server on {cfg.server.host}:{cfg.server.port}")
    uvicorn.run(
        fastapi_app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level=cfg.server.log_level,
        workers=cfg.server.workers,
    )


# ---------------------------------------------------------------------------
# embeddy ingest text
# ---------------------------------------------------------------------------


@ingest_app.command("text")
def ingest_text(
    text: str = typer.Argument(..., help="Text content to ingest."),
    collection: str = typer.Option("default", "--collection", "-C", help="Target collection."),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Source identifier."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Ingest raw text into a collection."""
    cfg = _resolve_config(config_path=config, db=db)
    cfg = cfg.model_copy(update={"pipeline": cfg.pipeline.model_copy(update={"collection": collection})})

    _, _, pipeline, _ = _build_deps(cfg)

    stats = asyncio.run(pipeline.ingest_text(text, source=source))
    typer.echo(_format_ingest_stats(stats, as_json=output_json))


# ---------------------------------------------------------------------------
# embeddy ingest file
# ---------------------------------------------------------------------------


@ingest_app.command("file")
def ingest_file(
    path: str = typer.Argument(..., help="Path to file to ingest."),
    collection: str = typer.Option("default", "--collection", "-C", help="Target collection."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Ingest a file into a collection."""
    file_path = Path(path)
    if not file_path.exists():
        typer.echo(f"Error: File not found: {path}", err=True)
        raise typer.Exit(code=1)

    cfg = _resolve_config(config_path=config, db=db)
    cfg = cfg.model_copy(update={"pipeline": cfg.pipeline.model_copy(update={"collection": collection})})

    _, _, pipeline, _ = _build_deps(cfg)

    stats = asyncio.run(pipeline.ingest_file(file_path))
    typer.echo(_format_ingest_stats(stats, as_json=output_json))


# ---------------------------------------------------------------------------
# embeddy ingest dir
# ---------------------------------------------------------------------------


@ingest_app.command("dir")
def ingest_dir(
    path: str = typer.Argument(..., help="Directory path to ingest."),
    collection: str = typer.Option("default", "--collection", "-C", help="Target collection."),
    include: Optional[str] = typer.Option(None, "--include", "-i", help="Include glob pattern (e.g. '*.py')."),
    exclude: Optional[str] = typer.Option(None, "--exclude", "-e", help="Exclude glob pattern (e.g. '*.pyc')."),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Recurse into subdirectories."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Ingest all files in a directory into a collection."""
    dir_path = Path(path)
    if not dir_path.is_dir():
        typer.echo(f"Error: Directory not found: {path}", err=True)
        raise typer.Exit(code=1)

    cfg = _resolve_config(config_path=config, db=db)
    cfg = cfg.model_copy(update={"pipeline": cfg.pipeline.model_copy(update={"collection": collection})})

    _, _, pipeline, _ = _build_deps(cfg)

    include_list = [include] if include else None
    exclude_list = [exclude] if exclude else None

    stats = asyncio.run(
        pipeline.ingest_directory(dir_path, include=include_list, exclude=exclude_list, recursive=recursive)
    )
    typer.echo(_format_ingest_stats(stats, as_json=output_json))


# ---------------------------------------------------------------------------
# embeddy search
# ---------------------------------------------------------------------------


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query."),
    collection: str = typer.Option("default", "--collection", "-C", help="Collection to search."),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of results."),
    mode: str = typer.Option("hybrid", "--mode", "-m", help="Search mode: vector, fulltext, hybrid."),
    min_score: Optional[float] = typer.Option(None, "--min-score", help="Minimum score threshold."),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Config file path."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON."),
) -> None:
    """Search a collection with vector, full-text, or hybrid search."""
    from embeddy.models import SearchMode

    mode_map = {
        "vector": SearchMode.VECTOR,
        "fulltext": SearchMode.FULLTEXT,
        "hybrid": SearchMode.HYBRID,
    }
    search_mode = mode_map.get(mode.lower())
    if search_mode is None:
        typer.echo(f"Error: Invalid mode '{mode}'. Choose from: vector, fulltext, hybrid.", err=True)
        raise typer.Exit(code=1)

    cfg = _resolve_config(config_path=config, db=db)
    _, _, _, search_service = _build_deps(cfg)

    results = asyncio.run(
        search_service.search(
            query=query,
            collection=collection,
            top_k=top_k,
            mode=search_mode,
            min_score=min_score,
        )
    )
    typer.echo(_format_search_results(results, as_json=output_json))
