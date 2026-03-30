# src/embeddy/models.py
"""Core data models for embeddy.

All data structures are Pydantic v2 BaseModels with validators. This module
defines the shared types used across all layers: embedding, ingestion,
chunking, storage, search, and pipeline.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ContentType(str, Enum):
    """Content type of an ingested document."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    GO = "go"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    RUBY = "ruby"
    SHELL = "shell"
    MARKDOWN = "markdown"
    RST = "rst"
    GENERIC = "generic"
    DOCLING = "docling"


class SearchMode(str, Enum):
    """Search mode for retrieval."""

    VECTOR = "vector"
    FULLTEXT = "fulltext"
    HYBRID = "hybrid"


class FusionStrategy(str, Enum):
    """Score fusion strategy for hybrid search."""

    RRF = "rrf"
    WEIGHTED = "weighted"


class DistanceMetric(str, Enum):
    """Distance/similarity metric for vector search."""

    COSINE = "cosine"
    DOT = "dot"


# ---------------------------------------------------------------------------
# Embedding models
# ---------------------------------------------------------------------------


class EmbedInput(BaseModel):
    """Multimodal input for embedding.

    At least one of ``text``, ``image``, or ``video`` must be provided.
    """

    text: str | None = None
    image: str | None = None  # File path, URL, or base64
    video: str | None = None  # File path or URL
    instruction: str | None = None  # Per-input instruction override

    @model_validator(mode="after")
    def validate_has_content(self) -> EmbedInput:
        """Ensure at least one input modality is provided."""
        if self.text is None and self.image is None and self.video is None:
            raise ValueError("At least one of 'text', 'image', or 'video' must be provided")
        return self


class Embedding(BaseModel):
    """A single embedding vector with associated metadata.

    Attributes:
        vector: The numeric embedding vector as a list of floats or numpy array.
        model_name: Identifier of the model that produced the embedding.
        normalized: Whether the vector has been L2-normalized.
        input_type: What type of input produced this embedding (text/image/video/multimodal).
    """

    model_config = {"arbitrary_types_allowed": True}

    vector: list[float] | np.ndarray = Field(description="Embedding vector representation")
    model_name: str = Field(description="Name of the model used to generate this embedding")
    normalized: bool = Field(default=True, description="Whether the vector is L2-normalized")
    input_type: str = Field(default="text", description="Input modality: text, image, video, multimodal")

    @field_validator("vector")
    @classmethod
    def validate_vector_not_empty(cls, value: list[float] | np.ndarray) -> list[float] | np.ndarray:
        """Ensure the embedding vector is not empty."""
        if isinstance(value, np.ndarray):
            if value.size == 0:
                raise ValueError("Embedding vector cannot be empty")
        elif len(value) == 0:
            raise ValueError("Embedding vector cannot be empty")
        return value

    @property
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vector."""
        if isinstance(self.vector, np.ndarray):
            if self.vector.ndim == 0:
                return 0
            return int(self.vector.shape[-1])
        return len(self.vector)

    def to_list(self) -> list[float]:
        """Return the vector as a plain list of floats."""
        if isinstance(self.vector, np.ndarray):
            return self.vector.tolist()
        return list(self.vector)


class SimilarityScore(BaseModel):
    """Similarity between two embeddings."""

    score: float = Field(description="Numeric similarity value")
    metric: str = Field(default="cosine", description="Similarity metric identifier")

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, value: str) -> str:
        allowed = {"cosine", "dot"}
        if value not in allowed:
            raise ValueError(f"Invalid similarity metric '{value}'. Must be one of {sorted(allowed)}")
        return value

    def _other_score(self, other: Any) -> float:
        if isinstance(other, SimilarityScore):
            return other.score
        if isinstance(other, (int, float)):
            return float(other)
        return NotImplemented  # type: ignore[return-value]

    def __lt__(self, other: Any) -> bool:
        s = self._other_score(other)
        if s is NotImplemented:  # type: ignore[comparison-overlap]
            return NotImplemented  # type: ignore[return-value]
        return self.score < s

    def __le__(self, other: Any) -> bool:
        s = self._other_score(other)
        if s is NotImplemented:  # type: ignore[comparison-overlap]
            return NotImplemented  # type: ignore[return-value]
        return self.score <= s

    def __gt__(self, other: Any) -> bool:
        s = self._other_score(other)
        if s is NotImplemented:  # type: ignore[comparison-overlap]
            return NotImplemented  # type: ignore[return-value]
        return self.score > s

    def __ge__(self, other: Any) -> bool:
        s = self._other_score(other)
        if s is NotImplemented:  # type: ignore[comparison-overlap]
            return NotImplemented  # type: ignore[return-value]
        return self.score >= s

    def __eq__(self, other: Any) -> bool:  # type: ignore[override]
        s = self._other_score(other)
        if s is NotImplemented:  # type: ignore[comparison-overlap]
            return NotImplemented  # type: ignore[return-value]
        return self.score == s


# ---------------------------------------------------------------------------
# Source & ingestion models
# ---------------------------------------------------------------------------


class SourceMetadata(BaseModel):
    """Metadata about the source of ingested content."""

    file_path: str | None = None
    url: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None  # SHA-256 for change detection / dedup


class IngestResult(BaseModel):
    """Result of ingesting a single document or text.

    Carries the raw/exported text, detected content type, source metadata,
    and optionally the structured Docling document.
    """

    text: str
    content_type: ContentType
    source: SourceMetadata = Field(default_factory=SourceMetadata)
    # DoclingDocument is typed as Any here to avoid importing docling at
    # module level. The actual type is enforced at runtime in the ingest layer.
    docling_document: Any | None = None


# ---------------------------------------------------------------------------
# Chunk models
# ---------------------------------------------------------------------------


def _generate_chunk_id() -> str:
    return str(uuid.uuid4())


class Chunk(BaseModel):
    """A chunk of content ready for embedding."""

    id: str = Field(default_factory=_generate_chunk_id)
    content: str
    content_type: ContentType
    chunk_type: str = Field(default="generic")  # function, class, heading_section, paragraph, window, etc.
    source: SourceMetadata = Field(default_factory=SourceMetadata)
    start_line: int | None = None
    end_line: int | None = None
    name: str | None = None  # Function/class name, heading text, etc.
    parent: str | None = None  # Parent class for methods, parent heading for subsections
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Chunk content cannot be empty or whitespace only")
        return value


# ---------------------------------------------------------------------------
# Collection models
# ---------------------------------------------------------------------------


class Collection(BaseModel):
    """A named collection of vectors in the store."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    dimension: int
    model_name: str
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Collection name cannot be empty")
        return value

    @field_validator("dimension")
    @classmethod
    def validate_dimension(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Collection dimension must be at least 1")
        return value


class CollectionStats(BaseModel):
    """Statistics about a collection."""

    name: str
    chunk_count: int = 0
    source_count: int = 0
    dimension: int = 0
    model_name: str = ""
    storage_bytes: int | None = None


# ---------------------------------------------------------------------------
# Search models
# ---------------------------------------------------------------------------


class SearchFilters(BaseModel):
    """Pre-filters applied before KNN or FTS search."""

    content_types: list[ContentType] | None = None
    source_path_prefix: str | None = None
    chunk_types: list[str] | None = None
    metadata_match: dict[str, Any] | None = None


class SearchResult(BaseModel):
    """A single search hit."""

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

    @field_validator("score")
    @classmethod
    def validate_score_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("SearchResult.score must be a finite float")
        return value


class SearchResults(BaseModel):
    """Container for search results."""

    results: list[SearchResult] = Field(default_factory=list)
    query: str = ""
    collection: str = ""
    mode: SearchMode = SearchMode.HYBRID
    total_results: int = 0
    elapsed_ms: float = 0.0

    @model_validator(mode="after")
    def validate_results_sorted(self) -> SearchResults:
        """Ensure results are sorted by score descending."""
        if len(self.results) >= 2:
            scores = [r.score for r in self.results]
            if scores != sorted(scores, reverse=True):
                raise ValueError("Search results must be sorted by score in descending order")
        return self


# ---------------------------------------------------------------------------
# Pipeline / ingestion stats
# ---------------------------------------------------------------------------


class IngestError(BaseModel):
    """An error that occurred during ingestion of a specific file."""

    file_path: str | None = None
    error: str
    error_type: str = ""


class IngestStats(BaseModel):
    """Statistics from a pipeline ingest operation."""

    files_processed: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    chunks_stored: int = 0
    chunks_skipped: int = 0  # Skipped due to content-hash dedup
    chunks_removed: int = 0  # Chunks deleted during reindex
    content_hash: str | None = None  # Content hash of the ingested source
    collection: str | None = None  # Target collection name
    errors: list[IngestError] = Field(default_factory=list)
    elapsed_seconds: float = 0.0
