# src/embeddy/server/schemas.py
"""Request and response Pydantic models for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from embeddy.models import (
    CollectionStats,
    FusionStrategy,
    SearchFilters,
    SearchMode,
)


# ---------------------------------------------------------------------------
# Embed
# ---------------------------------------------------------------------------


class EmbedInputSchema(BaseModel):
    """Single multimodal embed input."""

    text: str | None = None
    image: str | None = None
    video: str | None = None


class EmbedRequest(BaseModel):
    """Request body for POST /embed."""

    inputs: list[EmbedInputSchema]
    instruction: str | None = None


class EmbedResponse(BaseModel):
    """Response for POST /embed."""

    embeddings: list[list[float]]
    dimension: int
    model: str
    elapsed_ms: float


class EmbedQueryRequest(BaseModel):
    """Request body for POST /embed/query."""

    input: EmbedInputSchema
    instruction: str | None = None


class EmbedQueryResponse(BaseModel):
    """Response for POST /embed/query."""

    embedding: list[float]
    dimension: int
    model: str
    elapsed_ms: float


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    """Request body for POST /search."""

    query: str
    collection: str = "default"
    top_k: int = 10
    mode: SearchMode = SearchMode.HYBRID
    filters: SearchFilters | None = None
    min_score: float | None = None
    hybrid_alpha: float = 0.7
    fusion: FusionStrategy = FusionStrategy.RRF


class SearchResultItem(BaseModel):
    """Single search result in a response."""

    chunk_id: str
    content: str
    score: float
    source_path: str | None = None
    content_type: str | None = None
    chunk_type: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Response for POST /search."""

    results: list[SearchResultItem]
    query: str
    collection: str
    total_results: int
    mode: str
    elapsed_ms: float


class SimilarRequest(BaseModel):
    """Request body for POST /search/similar."""

    chunk_id: str
    collection: str = "default"
    top_k: int = 10
    exclude_self: bool = True


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class IngestTextRequest(BaseModel):
    """Request body for POST /ingest/text."""

    text: str
    collection: str = "default"
    source: str | None = None
    content_type: str | None = None


class IngestFileRequest(BaseModel):
    """Request body for POST /ingest/file."""

    path: str
    collection: str = "default"
    content_type: str | None = None


class IngestDirectoryRequest(BaseModel):
    """Request body for POST /ingest/directory."""

    path: str
    collection: str = "default"
    include: list[str] | None = None
    exclude: list[str] | None = None
    recursive: bool = True


class ReindexRequest(BaseModel):
    """Request body for POST /ingest/reindex."""

    path: str
    collection: str = "default"


class DeleteSourceRequest(BaseModel):
    """Request body for DELETE /ingest/source."""

    source_path: str
    collection: str = "default"


class IngestResponse(BaseModel):
    """Response for ingest operations."""

    files_processed: int
    chunks_created: int
    chunks_embedded: int
    chunks_stored: int
    chunks_skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_seconds: float


class DeleteSourceResponse(BaseModel):
    """Response for DELETE /ingest/source."""

    deleted_count: int


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


class CreateCollectionRequest(BaseModel):
    """Request body for POST /collections."""

    name: str
    metadata: dict[str, Any] | None = None


class CollectionItem(BaseModel):
    """Single collection in a list response."""

    id: str
    name: str
    dimension: int
    model_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionListResponse(BaseModel):
    """Response for GET /collections."""

    collections: list[CollectionItem]


class SourcesResponse(BaseModel):
    """Response for GET /collections/{name}/sources."""

    sources: list[str]


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class ChunkResponse(BaseModel):
    """Response for GET /chunks/{id}."""

    chunk_id: str
    content: str
    content_type: str | None = None
    chunk_type: str | None = None
    source_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    name: str | None = None
    parent: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None


# ---------------------------------------------------------------------------
# Health / Info
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: str = "ok"


class InfoResponse(BaseModel):
    """Response for GET /info."""

    version: str
    model_name: str
    dimension: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Structured error response."""

    error: str
    message: str
    details: dict[str, Any] | None = None
