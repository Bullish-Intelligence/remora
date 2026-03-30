# src/embeddy/cli/__init__.py
"""CLI sub-package for embeddy.

Re-exports the Typer ``app`` object so the entry point
``embeddy = embeddy.cli.main:app`` works.
"""

from __future__ import annotations

from embeddy.cli.main import app

__all__ = ["app"]
