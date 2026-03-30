# examples/wikipedia/ingest.py
"""Ingest Wikipedia articles into an embeddy pipeline.

This module takes downloaded articles and ingests them through the embeddy
pipeline (chunk -> embed -> store). It supports progress callbacks for
long-running ingestion jobs.

Usage (standalone)::

    python ingest.py --data-file ./data/articles.jsonl --db ./data/embeddy.db

"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from download import Article, load_articles

if TYPE_CHECKING:
    from embeddy.pipeline import Pipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ingestion stats
# ---------------------------------------------------------------------------


@dataclass
class IngestionStats:
    """Aggregate statistics from ingesting a batch of articles."""

    total_articles: int = 0
    total_chunks_created: int = 0
    total_chunks_embedded: int = 0
    total_chunks_stored: int = 0
    total_chunks_skipped: int = 0
    total_errors: int = 0
    elapsed_seconds: float = 0.0
    errors: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Build pipeline helper
# ---------------------------------------------------------------------------


def build_pipeline(
    db_path: str = "embeddy.db",
    collection: str = "wikipedia",
    model_name: str = "Qwen/Qwen3-Embedding-0.6B",
) -> Pipeline:
    """Build a real embeddy Pipeline from configuration.

    This is the default builder for standalone script use. Tests can bypass
    this by passing a mock pipeline directly to :func:`ingest_articles`.

    Args:
        db_path: Path to the SQLite database.
        collection: Collection name.
        model_name: Embedding model name.

    Returns:
        Configured Pipeline instance.
    """
    from embeddy.config import ChunkConfig, EmbedderConfig, StoreConfig
    from embeddy.embedding import Embedder
    from embeddy.pipeline import Pipeline
    from embeddy.store import VectorStore

    embedder_config = EmbedderConfig(model_name=model_name)
    store_config = StoreConfig(db_path=db_path)

    embedder = Embedder(embedder_config)
    store = VectorStore(store_config)

    return Pipeline(
        embedder=embedder,
        store=store,
        collection=collection,
        chunk_config=ChunkConfig(),
    )


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------


async def ingest_articles(
    articles: list[Article],
    pipeline: Pipeline,
    collection: str = "wikipedia",
    progress_callback: Callable[[int, int], None] | None = None,
) -> IngestionStats:
    """Ingest a list of articles through the pipeline.

    Each article is ingested as text with its title as the source identifier
    and metadata attached.

    Args:
        articles: List of Article objects to ingest.
        pipeline: The embeddy Pipeline to use.
        collection: Target collection name.
        progress_callback: Optional ``(current, total)`` callback for progress.

    Returns:
        Aggregate IngestionStats.
    """
    stats = IngestionStats()
    total = len(articles)
    start = time.monotonic()

    for i, article in enumerate(articles, 1):
        source = f"wikipedia:{article.article_id}"
        text = f"# {article.title}\n\n{article.text}"

        try:
            result = await pipeline.ingest_text(
                text=text,
                source=source,
            )
            stats.total_chunks_created += result.chunks_created
            stats.total_chunks_embedded += result.chunks_embedded
            stats.total_chunks_stored += result.chunks_stored
            stats.total_chunks_skipped += result.chunks_skipped

            if result.errors:
                for err in result.errors:
                    stats.total_errors += 1
                    stats.errors.append(
                        {
                            "article": article.title,
                            "error": err.error,
                            "error_type": err.error_type,
                        }
                    )

        except Exception as exc:
            stats.total_errors += 1
            stats.errors.append(
                {
                    "article": article.title,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            logger.error("Failed to ingest '%s': %s", article.title, exc)

        stats.total_articles = i

        if progress_callback is not None:
            progress_callback(i, total)

    stats.elapsed_seconds = time.monotonic() - start
    return stats


async def ingest_from_file(
    path: Path,
    pipeline: Pipeline,
    collection: str = "wikipedia",
    progress_callback: Callable[[int, int], None] | None = None,
) -> IngestionStats:
    """Load articles from a JSONL file and ingest them.

    Args:
        path: Path to the JSONL file.
        pipeline: The embeddy Pipeline to use.
        collection: Target collection name.
        progress_callback: Optional progress callback.

    Returns:
        Aggregate IngestionStats.
    """
    articles = load_articles(path)
    return await ingest_articles(
        articles,
        pipeline=pipeline,
        collection=collection,
        progress_callback=progress_callback,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Ingest Wikipedia articles into embeddy")
    parser.add_argument("--data-file", type=Path, default=Path("data/articles.jsonl"), help="JSONL file")
    parser.add_argument("--db", type=str, default="data/embeddy.db", help="SQLite DB path")
    parser.add_argument("--collection", type=str, default="wikipedia", help="Collection name")
    parser.add_argument("--model", type=str, default="Qwen/Qwen3-Embedding-0.6B", help="Embedding model")
    args = parser.parse_args()

    pipeline = build_pipeline(db_path=args.db, collection=args.collection, model_name=args.model)

    def on_progress(current: int, total: int) -> None:
        print(f"\r  [{current}/{total}] articles ingested", end="", flush=True)

    result = asyncio.run(
        ingest_from_file(args.data_file, pipeline=pipeline, collection=args.collection, progress_callback=on_progress)
    )
    print()
    print(f"Ingested {result.total_articles} articles")
    print(f"  Chunks created:  {result.total_chunks_created}")
    print(f"  Chunks embedded: {result.total_chunks_embedded}")
    print(f"  Chunks stored:   {result.total_chunks_stored}")
    print(f"  Chunks skipped:  {result.total_chunks_skipped}")
    print(f"  Errors:          {result.total_errors}")
    print(f"  Elapsed:         {result.elapsed_seconds:.2f}s")
