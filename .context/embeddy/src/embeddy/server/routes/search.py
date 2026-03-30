# src/embeddy/server/routes/search.py
"""Search endpoints — vector, fulltext, and hybrid search."""

from __future__ import annotations

from fastapi import APIRouter, Request

from embeddy.server.schemas import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SimilarRequest,
)

router = APIRouter(tags=["search"])


def _to_result_items(results: list) -> list[SearchResultItem]:
    """Convert SearchResult model objects to response items."""
    items = []
    for r in results:
        items.append(
            SearchResultItem(
                chunk_id=r.chunk_id,
                content=r.content,
                score=r.score,
                source_path=r.source_path,
                content_type=r.content_type,
                chunk_type=r.chunk_type,
                start_line=r.start_line,
                end_line=r.end_line,
                name=r.name,
                metadata=r.metadata,
            )
        )
    return items


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, request: Request) -> SearchResponse:
    """Search across a collection."""
    svc = request.app.state.search_service
    sr = await svc.search(
        body.query,
        body.collection,
        top_k=body.top_k,
        mode=body.mode,
        filters=body.filters,
        min_score=body.min_score,
        hybrid_alpha=body.hybrid_alpha,
        fusion=body.fusion,
    )
    return SearchResponse(
        results=_to_result_items(sr.results),
        query=sr.query,
        collection=sr.collection,
        total_results=sr.total_results,
        mode=sr.mode.value if hasattr(sr.mode, "value") else str(sr.mode),
        elapsed_ms=sr.elapsed_ms,
    )


@router.post("/search/similar", response_model=SearchResponse)
async def search_similar(body: SimilarRequest, request: Request) -> SearchResponse:
    """Find chunks similar to a given chunk."""
    svc = request.app.state.search_service
    sr = await svc.find_similar(
        body.chunk_id,
        body.collection,
        top_k=body.top_k,
        exclude_self=body.exclude_self,
    )
    return SearchResponse(
        results=_to_result_items(sr.results),
        query=sr.query,
        collection=sr.collection,
        total_results=sr.total_results,
        mode=sr.mode.value if hasattr(sr.mode, "value") else str(sr.mode),
        elapsed_ms=sr.elapsed_ms,
    )
