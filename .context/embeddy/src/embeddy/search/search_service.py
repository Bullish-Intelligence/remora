# src/embeddy/search/search_service.py
"""Async-native search service composing embedder + vector store.

The :class:`SearchService` provides vector (KNN), full-text (BM25), and
hybrid (RRF / weighted fusion) search over a collection.  It encodes the
query via the :class:`~embeddy.embedding.Embedder`, delegates retrieval to
the :class:`~embeddy.store.VectorStore`, and fuses results when in hybrid
mode.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from embeddy.models import (
    FusionStrategy,
    SearchFilters,
    SearchMode,
    SearchResult,
    SearchResults,
)

if TYPE_CHECKING:
    from embeddy.embedding import Embedder
    from embeddy.store import VectorStore

logger = logging.getLogger(__name__)

# Default RRF constant (standard in literature)
_RRF_K = 60


class SearchService:
    """Async-native search service composing embedder + store.

    Args:
        embedder: The embedding model facade.
        store: The vector store.
    """

    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    # ------------------------------------------------------------------
    # Main search dispatch
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        collection: str,
        top_k: int = 10,
        mode: SearchMode = SearchMode.HYBRID,
        filters: SearchFilters | None = None,
        min_score: float | None = None,
        hybrid_alpha: float = 0.7,
        fusion: FusionStrategy = FusionStrategy.RRF,
    ) -> SearchResults:
        """Search over a collection.

        Args:
            query: The search query text.
            collection: Target collection name.
            top_k: Maximum number of results to return.
            mode: Search mode — vector, fulltext, or hybrid.
            filters: Optional pre-filters.
            min_score: Minimum score threshold (results below are excluded).
            hybrid_alpha: Weight for vector vs BM25 in weighted fusion
                (0.0 = pure BM25, 1.0 = pure vector). Only used with
                ``fusion=FusionStrategy.WEIGHTED``.
            fusion: Score fusion strategy for hybrid mode (RRF or weighted).

        Returns:
            :class:`SearchResults` with ranked results.
        """
        if not query.strip():
            return SearchResults(
                results=[],
                query=query,
                collection=collection,
                mode=mode,
                total_results=0,
                elapsed_ms=0.0,
            )

        if mode == SearchMode.VECTOR:
            return await self.search_vector(
                query,
                collection,
                top_k=top_k,
                filters=filters,
                min_score=min_score,
            )
        elif mode == SearchMode.FULLTEXT:
            return await self.search_fulltext(
                query,
                collection,
                top_k=top_k,
                filters=filters,
                min_score=min_score,
            )
        else:
            return await self._search_hybrid(
                query,
                collection,
                top_k=top_k,
                filters=filters,
                min_score=min_score,
                hybrid_alpha=hybrid_alpha,
                fusion=fusion,
            )

    # ------------------------------------------------------------------
    # Vector (semantic) search
    # ------------------------------------------------------------------

    async def search_vector(
        self,
        query: str,
        collection: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
        min_score: float | None = None,
    ) -> SearchResults:
        """Pure vector/semantic search.

        Encodes the query, then performs KNN over the vector index.
        """
        start = time.monotonic()

        # Encode the query
        query_embedding = await self._embedder.encode_query(query)
        query_vector = query_embedding.to_list()

        # KNN search
        raw_results = await self._store.search_knn(
            collection_name=collection,
            query_vector=query_vector,
            top_k=top_k,
            filters=filters,
        )

        results = self._to_search_results(raw_results)

        # Apply min_score filter
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]

        # Truncate to top_k
        results = results[:top_k]

        elapsed = (time.monotonic() - start) * 1000

        return SearchResults(
            results=results,
            query=query,
            collection=collection,
            mode=SearchMode.VECTOR,
            total_results=len(results),
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Full-text (BM25) search
    # ------------------------------------------------------------------

    async def search_fulltext(
        self,
        query: str,
        collection: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
        min_score: float | None = None,
    ) -> SearchResults:
        """Pure full-text (BM25) search.

        Searches the FTS5 index directly — no embedding required.
        """
        start = time.monotonic()

        raw_results = await self._store.search_fts(
            collection_name=collection,
            query_text=query,
            top_k=top_k,
            filters=filters,
        )

        results = self._to_search_results(raw_results)

        # Apply min_score filter
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]

        results = results[:top_k]

        elapsed = (time.monotonic() - start) * 1000

        return SearchResults(
            results=results,
            query=query,
            collection=collection,
            mode=SearchMode.FULLTEXT,
            total_results=len(results),
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Hybrid search (vector + fulltext with fusion)
    # ------------------------------------------------------------------

    async def _search_hybrid(
        self,
        query: str,
        collection: str,
        top_k: int = 10,
        filters: SearchFilters | None = None,
        min_score: float | None = None,
        hybrid_alpha: float = 0.7,
        fusion: FusionStrategy = FusionStrategy.RRF,
    ) -> SearchResults:
        """Hybrid search: run both vector + fulltext, fuse, deduplicate, rank."""
        start = time.monotonic()

        # Encode the query for vector search
        query_embedding = await self._embedder.encode_query(query)
        query_vector = query_embedding.to_list()

        # Over-fetch from both backends to have enough candidates after fusion
        fetch_k = top_k * 3

        # Run both searches
        knn_raw = await self._store.search_knn(
            collection_name=collection,
            query_vector=query_vector,
            top_k=fetch_k,
            filters=filters,
        )
        fts_raw = await self._store.search_fts(
            collection_name=collection,
            query_text=query,
            top_k=fetch_k,
            filters=filters,
        )

        # Fuse results
        if fusion == FusionStrategy.RRF:
            fused = self._fuse_rrf(knn_raw, fts_raw)
        else:
            fused = self._fuse_weighted(knn_raw, fts_raw, alpha=hybrid_alpha)

        # Sort by fused score descending
        fused.sort(key=lambda r: r.score, reverse=True)

        # Apply min_score filter
        if min_score is not None:
            fused = [r for r in fused if r.score >= min_score]

        # Truncate to top_k
        fused = fused[:top_k]

        elapsed = (time.monotonic() - start) * 1000

        return SearchResults(
            results=fused,
            query=query,
            collection=collection,
            mode=SearchMode.HYBRID,
            total_results=len(fused),
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # find_similar
    # ------------------------------------------------------------------

    async def find_similar(
        self,
        chunk_id: str,
        collection: str,
        top_k: int = 10,
        exclude_self: bool = True,
    ) -> SearchResults:
        """Find chunks similar to an existing chunk (by ID).

        Retrieves the chunk, embeds its content, and performs KNN.

        Args:
            chunk_id: The ID of the source chunk.
            collection: Target collection.
            top_k: Maximum number of results.
            exclude_self: Whether to exclude the source chunk from results.

        Returns:
            :class:`SearchResults` with similar chunks.
        """
        start = time.monotonic()

        # Fetch the source chunk
        chunk_data = await self._store.get(collection, chunk_id)
        if chunk_data is None:
            elapsed = (time.monotonic() - start) * 1000
            return SearchResults(
                results=[],
                query=f"similar:{chunk_id}",
                collection=collection,
                mode=SearchMode.VECTOR,
                total_results=0,
                elapsed_ms=elapsed,
            )

        # Embed the chunk's content
        content = chunk_data.get("content", "")
        query_embedding = await self._embedder.encode_query(content)
        query_vector = query_embedding.to_list()

        # KNN search (fetch extra if excluding self)
        fetch_k = top_k + 1 if exclude_self else top_k
        raw_results = await self._store.search_knn(
            collection_name=collection,
            query_vector=query_vector,
            top_k=fetch_k,
        )

        results = self._to_search_results(raw_results)

        # Exclude self
        if exclude_self:
            results = [r for r in results if r.chunk_id != chunk_id]

        results = results[:top_k]

        elapsed = (time.monotonic() - start) * 1000

        return SearchResults(
            results=results,
            query=f"similar:{chunk_id}",
            collection=collection,
            mode=SearchMode.VECTOR,
            total_results=len(results),
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Score fusion strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _fuse_rrf(
        knn_results: list[dict[str, Any]],
        fts_results: list[dict[str, Any]],
    ) -> list[SearchResult]:
        """Reciprocal Rank Fusion (RRF).

        rrf_score(d) = sum(1 / (k + rank_i(d))) for each method i.
        """
        # Build rank maps (1-indexed)
        knn_ranks: dict[str, int] = {}
        knn_data: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(knn_results, start=1):
            cid = item["chunk_id"]
            knn_ranks[cid] = rank
            knn_data[cid] = item

        fts_ranks: dict[str, int] = {}
        fts_data: dict[str, dict[str, Any]] = {}
        for rank, item in enumerate(fts_results, start=1):
            cid = item["chunk_id"]
            fts_ranks[cid] = rank
            fts_data[cid] = item

        # Compute RRF scores for all unique chunk IDs
        all_ids = set(knn_ranks.keys()) | set(fts_ranks.keys())
        fused: list[SearchResult] = []

        for cid in all_ids:
            rrf_score = 0.0
            if cid in knn_ranks:
                rrf_score += 1.0 / (_RRF_K + knn_ranks[cid])
            if cid in fts_ranks:
                rrf_score += 1.0 / (_RRF_K + fts_ranks[cid])

            # Use data from whichever source has it (prefer KNN data)
            data = knn_data.get(cid) or fts_data.get(cid)
            assert data is not None

            fused.append(
                SearchResult(
                    chunk_id=data["chunk_id"],
                    content=data["content"],
                    score=rrf_score,
                    source_path=data.get("source_path"),
                    content_type=data.get("content_type"),
                    chunk_type=data.get("chunk_type"),
                    start_line=data.get("start_line"),
                    end_line=data.get("end_line"),
                    name=data.get("name"),
                    metadata=data.get("metadata", {}),
                )
            )

        return fused

    @staticmethod
    def _fuse_weighted(
        knn_results: list[dict[str, Any]],
        fts_results: list[dict[str, Any]],
        alpha: float = 0.7,
    ) -> list[SearchResult]:
        """Weighted linear combination of min-max normalized scores.

        alpha=1.0 means pure vector, alpha=0.0 means pure BM25.
        """
        # Min-max normalize KNN scores
        knn_scores: dict[str, float] = {}
        knn_data: dict[str, dict[str, Any]] = {}
        if knn_results:
            raw_scores = [item["score"] for item in knn_results]
            min_s, max_s = min(raw_scores), max(raw_scores)
            score_range = max_s - min_s if max_s > min_s else 1.0
            for item in knn_results:
                cid = item["chunk_id"]
                knn_scores[cid] = (item["score"] - min_s) / score_range
                knn_data[cid] = item

        # Min-max normalize FTS scores
        fts_scores: dict[str, float] = {}
        fts_data: dict[str, dict[str, Any]] = {}
        if fts_results:
            raw_scores = [item["score"] for item in fts_results]
            min_s, max_s = min(raw_scores), max(raw_scores)
            score_range = max_s - min_s if max_s > min_s else 1.0
            for item in fts_results:
                cid = item["chunk_id"]
                fts_scores[cid] = (item["score"] - min_s) / score_range
                fts_data[cid] = item

        # Combine
        all_ids = set(knn_scores.keys()) | set(fts_scores.keys())
        fused: list[SearchResult] = []

        for cid in all_ids:
            vec_score = knn_scores.get(cid, 0.0)
            text_score = fts_scores.get(cid, 0.0)
            combined = alpha * vec_score + (1.0 - alpha) * text_score

            data = knn_data.get(cid) or fts_data.get(cid)
            assert data is not None

            fused.append(
                SearchResult(
                    chunk_id=data["chunk_id"],
                    content=data["content"],
                    score=combined,
                    source_path=data.get("source_path"),
                    content_type=data.get("content_type"),
                    chunk_type=data.get("chunk_type"),
                    start_line=data.get("start_line"),
                    end_line=data.get("end_line"),
                    name=data.get("name"),
                    metadata=data.get("metadata", {}),
                )
            )

        return fused

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_search_results(raw: list[dict[str, Any]]) -> list[SearchResult]:
        """Convert raw store dicts to SearchResult models."""
        return [
            SearchResult(
                chunk_id=item["chunk_id"],
                content=item["content"],
                score=item["score"],
                source_path=item.get("source_path"),
                content_type=item.get("content_type"),
                chunk_type=item.get("chunk_type"),
                start_line=item.get("start_line"),
                end_line=item.get("end_line"),
                name=item.get("name"),
                metadata=item.get("metadata", {}),
            )
            for item in raw
        ]
