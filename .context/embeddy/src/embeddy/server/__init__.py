# src/embeddy/server/__init__.py
"""Server sub-package — FastAPI REST API for embeddy."""

from embeddy.server.app import create_app

__all__ = ["create_app"]
