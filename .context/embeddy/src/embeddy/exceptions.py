# src/embeddy/exceptions.py
"""Embeddy exception hierarchy.

All custom exceptions inherit from :class:`EmbeddyError` so that consumers
can catch a single base class for any library-specific error.
"""

from __future__ import annotations


class EmbeddyError(Exception):
    """Base exception for all embeddy errors."""


class ModelLoadError(EmbeddyError):
    """Raised when the embedding model fails to load.

    Typical causes include an invalid model path, missing model files,
    incompatible model formats, or insufficient resources (e.g. VRAM).
    """


class EncodingError(EmbeddyError):
    """Raised when encoding inputs into embeddings fails.

    Used for failures that occur while converting text, images, or video
    into embeddings, including invalid input values and underlying model
    errors.
    """


class ValidationError(EmbeddyError):
    """Raised when embeddy-specific validation fails.

    This is distinct from :class:`pydantic.ValidationError` and is used for
    domain-level validation errors such as dimension mismatches or invalid
    configuration combinations.
    """


class SearchError(EmbeddyError):
    """Raised when a search operation fails.

    Wraps errors that occur during similarity computation, vector search,
    full-text search, or hybrid score fusion.
    """


class IngestError(EmbeddyError):
    """Raised when document ingestion fails.

    Covers failures in file reading, content type detection, Docling
    document conversion, and content hash computation.
    """


class StoreError(EmbeddyError):
    """Raised when a vector store operation fails.

    Covers failures in database initialization, collection management,
    chunk CRUD, and index operations (sqlite-vec / FTS5).
    """


class ChunkingError(EmbeddyError):
    """Raised when document chunking fails.

    Covers failures in AST parsing, heading detection, token counting,
    and Docling chunker bridging.
    """


class ServerError(EmbeddyError):
    """Raised when the HTTP server encounters an error.

    Covers failures in server lifecycle (startup/shutdown), route handling,
    and dependency injection.
    """
