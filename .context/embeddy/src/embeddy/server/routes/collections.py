# src/embeddy/server/routes/collections.py
"""Collection management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from embeddy.server.schemas import (
    CollectionItem,
    CollectionListResponse,
    CreateCollectionRequest,
    SourcesResponse,
)

router = APIRouter(tags=["collections"])


def _collection_to_item(coll) -> CollectionItem:
    """Convert a Collection model to the response item schema."""
    return CollectionItem(
        id=coll.id,
        name=coll.name,
        dimension=coll.dimension,
        model_name=coll.model_name,
        metadata=getattr(coll, "metadata", {}),
    )


@router.get("/collections", response_model=CollectionListResponse)
async def list_collections(request: Request) -> CollectionListResponse:
    """List all collections."""
    store = request.app.state.store
    colls = await store.list_collections()
    return CollectionListResponse(collections=[_collection_to_item(c) for c in colls])


@router.post("/collections", status_code=201)
async def create_collection(body: CreateCollectionRequest, request: Request) -> CollectionItem:
    """Create a new collection."""
    store = request.app.state.store
    embedder = request.app.state.embedder
    coll = await store.create_collection(
        body.name,
        dimension=embedder.dimension,
        model_name=embedder.model_name,
    )
    return _collection_to_item(coll)


@router.get("/collections/{name}", response_model=None)
async def get_collection(name: str, request: Request) -> CollectionItem | JSONResponse:
    """Get a single collection by name."""
    store = request.app.state.store
    coll = await store.get_collection(name)
    if coll is None:
        return JSONResponse(
            status_code=404, content={"error": "not_found", "message": f"Collection '{name}' not found"}
        )
    return _collection_to_item(coll)


@router.delete("/collections/{name}")
async def delete_collection(name: str, request: Request) -> JSONResponse:
    """Delete a collection by name."""
    store = request.app.state.store
    coll = await store.get_collection(name)
    if coll is None:
        return JSONResponse(
            status_code=404, content={"error": "not_found", "message": f"Collection '{name}' not found"}
        )
    await store.delete_collection(name)
    return JSONResponse(status_code=200, content={"message": f"Collection '{name}' deleted"})


@router.get("/collections/{name}/sources", response_model=None)
async def collection_sources(name: str, request: Request) -> SourcesResponse | JSONResponse:
    """List all source paths in a collection."""
    store = request.app.state.store
    coll = await store.get_collection(name)
    if coll is None:
        return JSONResponse(
            status_code=404, content={"error": "not_found", "message": f"Collection '{name}' not found"}
        )
    sources = await store.list_sources(name)
    return SourcesResponse(sources=sources)


@router.get("/collections/{name}/stats")
async def collection_stats(name: str, request: Request) -> JSONResponse:
    """Get statistics for a collection."""
    store = request.app.state.store
    coll = await store.get_collection(name)
    if coll is None:
        return JSONResponse(
            status_code=404, content={"error": "not_found", "message": f"Collection '{name}' not found"}
        )
    stats = await store.stats(name)
    # CollectionStats is a Pydantic model — serialize it
    if hasattr(stats, "model_dump"):
        return JSONResponse(status_code=200, content=stats.model_dump())
    # Fallback for plain dicts
    return JSONResponse(status_code=200, content=dict(stats))
