# examples/wikipedia/search.py
"""Interactive search over ingested Wikipedia articles.

Provides both a programmatic interface and an interactive CLI for searching
the Wikipedia collection.

Usage (standalone)::

    python search.py --query "what is machine learning" --top-k 5
    python search.py --interactive

"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING

from embeddy.models import SearchMode, SearchResults

if TYPE_CHECKING:
    from embeddy.search import SearchService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search function
# ---------------------------------------------------------------------------


async def search_articles(
    query: str,
    search_service: SearchService,
    collection: str = "wikipedia",
    top_k: int = 10,
    mode: SearchMode = SearchMode.HYBRID,
) -> SearchResults:
    """Search for articles matching a query.

    Args:
        query: The search query string.
        search_service: An embeddy SearchService instance.
        collection: Collection to search.
        top_k: Number of results to return.
        mode: Search mode (vector, fulltext, or hybrid).

    Returns:
        SearchResults with matching chunks.
    """
    return await search_service.search(
        query=query,
        collection=collection,
        top_k=top_k,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_results(results: SearchResults) -> str:
    """Format search results for human-readable terminal output.

    Args:
        results: The SearchResults to format.

    Returns:
        Formatted string.
    """
    lines: list[str] = []

    if not results.results:
        lines.append(f'No results found for query: "{results.query}"')
        lines.append(f"  Collection: {results.collection}")
        lines.append(f"  Mode: {results.mode.value}")
        lines.append(f"  Elapsed: {results.elapsed_ms:.1f}ms")
        return "\n".join(lines)

    lines.append(
        f'{results.total_results} result(s) for "{results.query}" [{results.mode.value}, {results.elapsed_ms:.1f}ms]'
    )
    lines.append("")

    for i, result in enumerate(results.results, 1):
        title = result.metadata.get("title", "Unknown") if result.metadata else "Unknown"
        score_str = f"{result.score:.4f}" if result.score is not None else "N/A"

        lines.append(f"  {i}. [{score_str}] {title}")
        lines.append(f"     Source: {result.source_path}")

        # Show a snippet of the content (first 200 chars)
        snippet = result.content[:200].replace("\n", " ")
        if len(result.content) > 200:
            snippet += "..."
        lines.append(f"     {snippet}")
        lines.append("")

    return "\n".join(lines)


def format_results_json(results: SearchResults) -> str:
    """Format search results as a JSON string.

    Args:
        results: The SearchResults to format.

    Returns:
        JSON string.
    """
    output = {
        "query": results.query,
        "collection": results.collection,
        "mode": results.mode.value,
        "total_results": results.total_results,
        "elapsed_ms": results.elapsed_ms,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "score": r.score,
                "source": r.source_path,
                "title": r.metadata.get("title") if r.metadata else None,
                "content": r.content,
            }
            for r in results.results
        ],
    }
    return json.dumps(output, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from embeddy.config import EmbedderConfig, StoreConfig
    from embeddy.embedding import Embedder
    from embeddy.search import SearchService
    from embeddy.store import VectorStore

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Search Wikipedia articles in embeddy")
    parser.add_argument("--query", "-q", type=str, help="Search query")
    parser.add_argument("--top-k", "-k", type=int, default=5, help="Number of results")
    parser.add_argument("--mode", "-m", type=str, default="hybrid", choices=["vector", "fulltext", "hybrid"])
    parser.add_argument("--collection", type=str, default="wikipedia", help="Collection name")
    parser.add_argument("--db", type=str, default="data/embeddy.db", help="SQLite DB path")
    parser.add_argument("--model", type=str, default="Qwen/Qwen3-Embedding-0.6B", help="Embedding model")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive search mode")
    args = parser.parse_args()

    embedder_config = EmbedderConfig(model_name=args.model)
    store_config = StoreConfig(db_path=args.db)
    embedder = Embedder(embedder_config)
    store = VectorStore(store_config)
    service = SearchService(embedder=embedder, store=store)

    search_mode = SearchMode(args.mode)

    async def _run_query(q: str) -> None:
        results = await search_articles(
            q, search_service=service, collection=args.collection, top_k=args.top_k, mode=search_mode
        )
        if args.json:
            print(format_results_json(results))
        else:
            print(format_results(results))

    if args.interactive:
        print("Wikipedia Search (type 'quit' to exit)")
        print("-" * 40)
        while True:
            try:
                query = input("\nQuery: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if query.lower() in ("quit", "exit", "q"):
                print("Bye!")
                break
            if not query:
                continue
            asyncio.run(_run_query(query))
    elif args.query:
        asyncio.run(_run_query(args.query))
    else:
        parser.print_help()
        sys.exit(1)
