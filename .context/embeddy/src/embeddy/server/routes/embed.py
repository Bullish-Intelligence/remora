# src/embeddy/server/routes/embed.py
"""Embed endpoints — vectorize text inputs."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from embeddy.server.schemas import (
    EmbedQueryRequest,
    EmbedQueryResponse,
    EmbedRequest,
    EmbedResponse,
)

router = APIRouter(tags=["embed"])


@router.post("/embed", response_model=None)
async def embed(body: EmbedRequest, request: Request) -> EmbedResponse | JSONResponse:
    """Embed a batch of inputs."""
    if not body.inputs:
        return JSONResponse(
            status_code=400, content={"error": "validation_error", "message": "inputs must not be empty"}
        )

    embedder = request.app.state.embedder
    t0 = time.monotonic()
    results = await embedder.encode(body.inputs, instruction=body.instruction)
    elapsed_ms = (time.monotonic() - t0) * 1000

    return EmbedResponse(
        embeddings=[emb.to_list() for emb in results],
        dimension=embedder.dimension,
        model=embedder.model_name,
        elapsed_ms=round(elapsed_ms, 2),
    )


@router.post("/embed/query", response_model=EmbedQueryResponse)
async def embed_query(body: EmbedQueryRequest, request: Request) -> EmbedQueryResponse:
    """Embed a single query input (with query instruction)."""
    embedder = request.app.state.embedder
    t0 = time.monotonic()
    result = await embedder.encode_query(body.input.text)
    elapsed_ms = (time.monotonic() - t0) * 1000

    return EmbedQueryResponse(
        embedding=result.to_list(),
        dimension=embedder.dimension,
        model=embedder.model_name,
        elapsed_ms=round(elapsed_ms, 2),
    )
