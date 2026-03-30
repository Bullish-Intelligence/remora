"""Web middleware components."""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _is_allowed_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject mutating requests from non-local browser origins."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if request.method in {"POST", "PUT", "DELETE"}:
            origin = request.headers.get("origin", "").strip()
            if origin and not _is_allowed_origin(origin):
                return JSONResponse({"error": "CSRF rejected"}, status_code=403)
        return await call_next(request)


# Note: no CORS headers are intentionally set.
# Cross-origin browser requests requiring preflight (for example POST/PUT/DELETE)
# fail by default. Remora is designed for localhost access only. If cross-origin
# browser access is required, add Starlette CORSMiddleware explicitly.
__all__ = ["CSRFMiddleware"]
