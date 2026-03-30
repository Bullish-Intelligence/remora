# src/embeddy/server/app.py
"""FastAPI application factory for the embeddy server.

The :func:`create_app` factory accepts pre-built dependencies (embedder,
store, pipeline, search_service) and wires them into route handlers via
FastAPI's ``app.state``.  This makes the server trivially testable — tests
inject mocks, production code injects real objects.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import embeddy
from embeddy.exceptions import (
    ChunkingError,
    EmbeddyError,
    EncodingError,
    IngestError,
    ModelLoadError,
    SearchError,
    StoreError,
    ValidationError,
)
from embeddy.server.routes import health, embed, search, ingest, collections, chunks

if TYPE_CHECKING:
    from embeddy.embedding import Embedder
    from embeddy.pipeline import Pipeline
    from embeddy.search import SearchService
    from embeddy.store import VectorStore

logger = logging.getLogger(__name__)

# Map exception types to (HTTP status, error key)
_ERROR_MAP: dict[type[EmbeddyError], tuple[int, str]] = {
    ValidationError: (400, "validation_error"),
    ModelLoadError: (500, "model_load_error"),
    EncodingError: (500, "encoding_error"),
    SearchError: (500, "search_error"),
    IngestError: (500, "ingest_error"),
    StoreError: (500, "store_error"),
    ChunkingError: (500, "chunking_error"),
}


def create_app(
    *,
    embedder: Embedder,
    store: VectorStore,
    pipeline: Pipeline,
    search_service: SearchService,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        embedder: The embedding model facade.
        store: The vector store.
        pipeline: The ingest pipeline.
        search_service: The search service.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="embeddy",
        version=embeddy.__version__,
        description="Async-native embedding, chunking, hybrid search, and RAG pipeline.",
    )

    # Store dependencies on app.state for route access
    app.state.embedder = embedder
    app.state.store = store
    app.state.pipeline = pipeline
    app.state.search_service = search_service

    # ------------------------------------------------------------------
    # Exception handlers
    # ------------------------------------------------------------------

    @app.exception_handler(EmbeddyError)
    async def embeddy_error_handler(request: Request, exc: EmbeddyError) -> JSONResponse:
        """Map EmbeddyError subclasses to structured JSON error responses."""
        status_code = 500
        error_key = "embeddy_error"

        for exc_type, (code, key) in _ERROR_MAP.items():
            if isinstance(exc, exc_type):
                status_code = code
                error_key = key
                break

        return JSONResponse(
            status_code=status_code,
            content={"error": error_key, "message": str(exc)},
        )

    # ------------------------------------------------------------------
    # Mount route modules
    # ------------------------------------------------------------------

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(embed.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(ingest.router, prefix="/api/v1")
    app.include_router(collections.router, prefix="/api/v1")
    app.include_router(chunks.router, prefix="/api/v1")

    return app
