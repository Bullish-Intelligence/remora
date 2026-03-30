# examples/wikipedia/benchmark.py
"""Benchmark embeddy performance over a Wikipedia dataset.

Measures ingestion throughput, search latency, and resource usage
across different configurations and search modes.

Usage (standalone)::

    python benchmark.py --data-file ./data/articles.jsonl --db ./data/bench.db

"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from download import Article

if TYPE_CHECKING:
    from embeddy.pipeline import Pipeline
    from embeddy.search import SearchService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark runs."""

    num_articles: int = 100
    num_queries: int = 20
    collection: str = "wikipedia_bench"
    search_modes: list[str] = field(default_factory=lambda: ["vector", "fulltext", "hybrid"])
    top_k_values: list[int] = field(default_factory=lambda: [5, 10, 20])


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class IngestBenchmarkResult:
    """Results from an ingestion benchmark run."""

    total_articles: int = 0
    total_chunks: int = 0
    elapsed_seconds: float = 0.0
    articles_per_second: float = 0.0
    chunks_per_second: float = 0.0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModeLatencyStats:
    """Latency statistics for a single search mode."""

    mode: str = ""
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    queries_per_second: float = 0.0


@dataclass
class SearchBenchmarkResult:
    """Results from a search benchmark run."""

    total_queries: int = 0
    elapsed_seconds: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    queries_per_second: float = 0.0
    per_mode: dict[str, ModeLatencyStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Convert ModeLatencyStats to dicts
        d["per_mode"] = {k: asdict(v) for k, v in self.per_mode.items()}
        return d


# ---------------------------------------------------------------------------
# Ingest benchmark
# ---------------------------------------------------------------------------


async def run_ingest_benchmark(
    articles: list[Article],
    pipeline: Pipeline,
    config: BenchmarkConfig | None = None,
) -> IngestBenchmarkResult:
    """Benchmark ingestion throughput.

    Args:
        articles: Articles to ingest.
        pipeline: The embeddy Pipeline.
        config: Benchmark configuration.

    Returns:
        IngestBenchmarkResult with throughput metrics.
    """
    config = config or BenchmarkConfig()
    batch = articles[: config.num_articles]
    result = IngestBenchmarkResult()

    start = time.monotonic()
    total_chunks = 0
    total_errors = 0

    for article in batch:
        source = f"wikipedia:{article.article_id}"
        text = f"# {article.title}\n\n{article.text}"

        try:
            stats = await pipeline.ingest_text(text=text, source=source)
            total_chunks += stats.chunks_created
            if stats.errors:
                total_errors += len(stats.errors)
        except Exception as exc:
            total_errors += 1
            logger.error("Benchmark ingest error for '%s': %s", article.title, exc)

    elapsed = time.monotonic() - start

    result.total_articles = len(batch)
    result.total_chunks = total_chunks
    result.elapsed_seconds = elapsed
    result.articles_per_second = len(batch) / elapsed if elapsed > 0 else 0
    result.chunks_per_second = total_chunks / elapsed if elapsed > 0 else 0
    result.errors = total_errors

    return result


# ---------------------------------------------------------------------------
# Search benchmark
# ---------------------------------------------------------------------------


def _percentile(data: list[float], pct: float) -> float:
    """Calculate the given percentile from a sorted list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (pct / 100.0) * (len(sorted_data) - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= len(sorted_data):
        return sorted_data[-1]
    weight = idx - lower
    return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight


async def run_search_benchmark(
    queries: list[str],
    search_service: SearchService,
    config: BenchmarkConfig | None = None,
) -> SearchBenchmarkResult:
    """Benchmark search latency across modes.

    Args:
        queries: List of query strings.
        search_service: The embeddy SearchService.
        config: Benchmark configuration.

    Returns:
        SearchBenchmarkResult with latency metrics.
    """
    from embeddy.models import SearchMode

    config = config or BenchmarkConfig()
    batch = queries[: config.num_queries]
    modes = config.search_modes

    result = SearchBenchmarkResult()
    all_latencies: list[float] = []
    per_mode_latencies: dict[str, list[float]] = {m: [] for m in modes}

    start = time.monotonic()
    total_queries = 0

    for mode_str in modes:
        mode = SearchMode(mode_str)
        for query in batch:
            q_start = time.monotonic()
            try:
                await search_service.search(
                    query=query,
                    collection=config.collection,
                    top_k=10,
                    mode=mode,
                )
            except Exception as exc:
                logger.error("Benchmark search error: %s", exc)
            q_elapsed_ms = (time.monotonic() - q_start) * 1000
            all_latencies.append(q_elapsed_ms)
            per_mode_latencies[mode_str].append(q_elapsed_ms)
            total_queries += 1

    elapsed = time.monotonic() - start

    result.total_queries = total_queries
    result.elapsed_seconds = elapsed

    if all_latencies:
        result.avg_latency_ms = statistics.mean(all_latencies)
        result.p50_latency_ms = _percentile(all_latencies, 50)
        result.p95_latency_ms = _percentile(all_latencies, 95)
        result.p99_latency_ms = _percentile(all_latencies, 99)

    result.queries_per_second = total_queries / elapsed if elapsed > 0 else 0

    # Per-mode stats
    for mode_str, latencies in per_mode_latencies.items():
        if latencies:
            mode_stats = ModeLatencyStats(
                mode=mode_str,
                avg_ms=statistics.mean(latencies),
                p50_ms=_percentile(latencies, 50),
                p95_ms=_percentile(latencies, 95),
                p99_ms=_percentile(latencies, 99),
                queries_per_second=len(latencies) / (sum(latencies) / 1000) if sum(latencies) > 0 else 0,
            )
            result.per_mode[mode_str] = mode_stats

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import json as json_mod

    from download import load_articles
    from ingest import build_pipeline

    from embeddy.config import EmbedderConfig, StoreConfig
    from embeddy.embedding import Embedder
    from embeddy.search import SearchService
    from embeddy.store import VectorStore

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Benchmark embeddy with Wikipedia data")
    parser.add_argument("--data-file", type=Path, default=Path("data/articles.jsonl"), help="JSONL file")
    parser.add_argument("--db", type=str, default="data/bench.db", help="SQLite DB path")
    parser.add_argument("--collection", type=str, default="wikipedia_bench", help="Collection name")
    parser.add_argument("--model", type=str, default="Qwen/Qwen3-Embedding-0.6B", help="Embedding model")
    parser.add_argument("--num-articles", type=int, default=100, help="Number of articles to ingest")
    parser.add_argument("--num-queries", type=int, default=20, help="Number of queries for search bench")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    articles = load_articles(args.data_file)
    config = BenchmarkConfig(
        num_articles=args.num_articles,
        num_queries=args.num_queries,
        collection=args.collection,
    )

    pipeline = build_pipeline(db_path=args.db, collection=args.collection, model_name=args.model)

    embedder_config = EmbedderConfig(model_name=args.model)
    store_config = StoreConfig(db_path=args.db)
    embedder = Embedder(embedder_config)
    store = VectorStore(store_config)
    search_service = SearchService(embedder=embedder, store=store)

    # Run ingest benchmark
    print("Running ingestion benchmark...")
    ingest_result = asyncio.run(run_ingest_benchmark(articles, pipeline=pipeline, config=config))

    # Generate sample queries from article titles
    sample_queries = [a.title for a in articles[: config.num_queries]]

    # Run search benchmark
    print("Running search benchmark...")
    search_result = asyncio.run(run_search_benchmark(sample_queries, search_service=search_service, config=config))

    if args.json:
        output = {
            "ingest": ingest_result.to_dict(),
            "search": search_result.to_dict(),
        }
        print(json_mod.dumps(output, indent=2))
    else:
        print("\n=== Ingest Benchmark ===")
        print(f"  Articles:          {ingest_result.total_articles}")
        print(f"  Chunks:            {ingest_result.total_chunks}")
        print(f"  Elapsed:           {ingest_result.elapsed_seconds:.2f}s")
        print(f"  Articles/sec:      {ingest_result.articles_per_second:.1f}")
        print(f"  Chunks/sec:        {ingest_result.chunks_per_second:.1f}")
        print(f"  Errors:            {ingest_result.errors}")

        print("\n=== Search Benchmark ===")
        print(f"  Total queries:     {search_result.total_queries}")
        print(f"  Elapsed:           {search_result.elapsed_seconds:.2f}s")
        print(f"  Avg latency:       {search_result.avg_latency_ms:.1f}ms")
        print(f"  P50 latency:       {search_result.p50_latency_ms:.1f}ms")
        print(f"  P95 latency:       {search_result.p95_latency_ms:.1f}ms")
        print(f"  P99 latency:       {search_result.p99_latency_ms:.1f}ms")
        print(f"  Queries/sec:       {search_result.queries_per_second:.1f}")

        if search_result.per_mode:
            print("\n  Per-mode breakdown:")
            for mode, stats in search_result.per_mode.items():
                print(f"    {mode}: avg={stats.avg_ms:.1f}ms, p50={stats.p50_ms:.1f}ms, p95={stats.p95_ms:.1f}ms")
