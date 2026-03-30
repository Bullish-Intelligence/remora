# src/embeddy/server/routes/chunks.py
"""Chunk endpoints — get and delete individual chunks."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from embeddy.server.schemas import ChunkResponse

router = APIRouter(tags=["chunks"])


@router.get("/chunks/{chunk_id}", response_model=None)
async def get_chunk(
    chunk_id: str,
    request: Request,
    collection: str = Query(default="default"),
) -> ChunkResponse | JSONResponse:
    """Get a single chunk by ID."""
    store = request.app.state.store
    row = await store.get(collection, chunk_id)
    if row is None:
        return JSONResponse(status_code=404, content={"error": "not_found", "message": f"Chunk '{chunk_id}' not found"})
    return ChunkResponse(**row)


@router.delete("/chunks/{chunk_id}")
async def delete_chunk(
    chunk_id: str,
    request: Request,
    collection: str = Query(default="default"),
) -> JSONResponse:
    """Delete a single chunk by ID."""
    store = request.app.state.store
    await store.delete(collection, [chunk_id])
    return JSONResponse(status_code=200, content={"message": f"Chunk '{chunk_id}' deleted"})
