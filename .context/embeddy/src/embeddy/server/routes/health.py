# src/embeddy/server/routes/health.py
"""Health and info endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

import embeddy
from embeddy.server.schemas import HealthResponse, InfoResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check."""
    return HealthResponse(status="ok")


@router.get("/info", response_model=InfoResponse)
async def info(request: Request) -> InfoResponse:
    """Server information."""
    emb = request.app.state.embedder
    return InfoResponse(
        version=embeddy.__version__,
        model_name=emb.model_name,
        dimension=emb.dimension,
    )
