# src/embeddy/server/routes/ingest.py
"""Ingest endpoints — text, file, directory, reindex, delete source."""

from __future__ import annotations

from fastapi import APIRouter, Request

from embeddy.server.schemas import (
    DeleteSourceRequest,
    DeleteSourceResponse,
    IngestDirectoryRequest,
    IngestFileRequest,
    IngestResponse,
    IngestTextRequest,
    ReindexRequest,
)

router = APIRouter(tags=["ingest"])


def _stats_to_response(stats) -> IngestResponse:
    """Convert an IngestStats model to the response schema."""
    errors = []
    for e in stats.errors:
        errors.append({"file_path": e.file_path, "error": e.error, "error_type": e.error_type})
    return IngestResponse(
        files_processed=stats.files_processed,
        chunks_created=stats.chunks_created,
        chunks_embedded=stats.chunks_embedded,
        chunks_stored=stats.chunks_stored,
        chunks_skipped=stats.chunks_skipped,
        errors=errors,
        elapsed_seconds=stats.elapsed_seconds,
    )


@router.post("/ingest/text", response_model=IngestResponse)
async def ingest_text(body: IngestTextRequest, request: Request) -> IngestResponse:
    """Ingest raw text."""
    pipeline = request.app.state.pipeline
    stats = await pipeline.ingest_text(
        body.text,
        source=body.source,
        content_type=body.content_type,
    )
    return _stats_to_response(stats)


@router.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(body: IngestFileRequest, request: Request) -> IngestResponse:
    """Ingest a single file."""
    pipeline = request.app.state.pipeline
    stats = await pipeline.ingest_file(
        body.path,
        content_type=body.content_type,
    )
    return _stats_to_response(stats)


@router.post("/ingest/directory", response_model=IngestResponse)
async def ingest_directory(body: IngestDirectoryRequest, request: Request) -> IngestResponse:
    """Ingest all files in a directory."""
    pipeline = request.app.state.pipeline
    stats = await pipeline.ingest_directory(
        body.path,
        include=body.include,
        exclude=body.exclude,
        recursive=body.recursive,
    )
    return _stats_to_response(stats)


@router.post("/ingest/reindex", response_model=IngestResponse)
async def reindex(body: ReindexRequest, request: Request) -> IngestResponse:
    """Reindex a file (delete old chunks and re-ingest)."""
    pipeline = request.app.state.pipeline
    stats = await pipeline.reindex_file(body.path)
    return _stats_to_response(stats)


@router.delete("/ingest/source", response_model=DeleteSourceResponse)
async def delete_source(body: DeleteSourceRequest, request: Request) -> DeleteSourceResponse:
    """Delete all chunks from a source."""
    pipeline = request.app.state.pipeline
    count = await pipeline.delete_source(body.source_path)
    return DeleteSourceResponse(deleted_count=count)
