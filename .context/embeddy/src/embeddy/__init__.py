# src/embeddy/__init__.py
"""Public package interface for embeddy.

Re-exports the core types, configuration, and exceptions that consumers
are expected to import from the top-level package.
"""

from __future__ import annotations

from embeddy.config import (
    ChunkConfig,
    EmbedderConfig,
    EmbeddyConfig,
    PipelineConfig,
    ServerConfig,
    StoreConfig,
    load_config_file,
)
from embeddy.chunking import (
    BaseChunker,
    DoclingChunker,
    MarkdownChunker,
    ParagraphChunker,
    PythonChunker,
    TokenWindowChunker,
    get_chunker,
)
from embeddy.embedding import Embedder, EmbedderBackend, LocalBackend, RemoteBackend
from embeddy.ingest import (
    Ingestor,
    compute_content_hash,
    detect_content_type,
    is_docling_path,
)
from embeddy.pipeline import Pipeline
from embeddy.search import SearchService
from embeddy.client import EmbeddyClient
from embeddy.server import create_app
from embeddy.store import VectorStore
from embeddy.exceptions import (
    ChunkingError,
    EmbeddyError,
    EncodingError,
    IngestError,
    ModelLoadError,
    SearchError,
    ServerError,
    StoreError,
    ValidationError,
)
from embeddy.models import (
    Chunk,
    Collection,
    CollectionStats,
    ContentType,
    DistanceMetric,
    EmbedInput,
    Embedding,
    FusionStrategy,
    IngestResult,
    IngestStats,
    SearchFilters,
    SearchMode,
    SearchResult,
    SearchResults,
    SimilarityScore,
    SourceMetadata,
)

__version__ = "0.3.12"

__all__ = [
    # Version
    "__version__",
    # Config
    "EmbedderConfig",
    "StoreConfig",
    "ChunkConfig",
    "PipelineConfig",
    "ServerConfig",
    "EmbeddyConfig",
    "load_config_file",
    # Models - enums
    "ContentType",
    "SearchMode",
    "FusionStrategy",
    "DistanceMetric",
    # Embedding layer
    "Embedder",
    "EmbedderBackend",
    "LocalBackend",
    "RemoteBackend",
    # Chunking layer
    "BaseChunker",
    "PythonChunker",
    "MarkdownChunker",
    "ParagraphChunker",
    "TokenWindowChunker",
    "DoclingChunker",
    "get_chunker",
    # Store layer
    "VectorStore",
    # Pipeline layer
    "Pipeline",
    # Search layer
    "SearchService",
    # Server layer
    "create_app",
    # Client layer
    "EmbeddyClient",
    # Ingest layer
    "Ingestor",
    "compute_content_hash",
    "detect_content_type",
    "is_docling_path",
    # Models - embedding
    "EmbedInput",
    "Embedding",
    "SimilarityScore",
    # Models - ingestion
    "SourceMetadata",
    "IngestResult",
    # Models - chunks
    "Chunk",
    # Models - collections
    "Collection",
    "CollectionStats",
    # Models - search
    "SearchFilters",
    "SearchResult",
    "SearchResults",
    # Models - pipeline
    "IngestStats",
    # Exceptions
    "EmbeddyError",
    "ModelLoadError",
    "EncodingError",
    "ValidationError",
    "SearchError",
    "IngestError",
    "StoreError",
    "ChunkingError",
    "ServerError",
]
