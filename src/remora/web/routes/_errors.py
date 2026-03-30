"""Shared API error response helpers for web routes."""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse


def error_response(
    *,
    error: str,
    message: str,
    status_code: int,
    docs: str | None = None,
    extras: dict[str, Any] | None = None,
) -> JSONResponse:
    payload: dict[str, Any] = {
        "error": error,
        "message": message,
    }
    if docs:
        payload["docs"] = docs
    if extras:
        payload.update(extras)
    return JSONResponse(payload, status_code=status_code)


__all__ = ["error_response"]
