# src/embeddy/ingest/__init__.py
"""Document ingestion layer.

Provides the :class:`Ingestor` for accepting files and raw text, and
helper utilities for content type detection and hashing.
"""

from __future__ import annotations

from embeddy.ingest.ingestor import (
    Ingestor,
    compute_content_hash,
    detect_content_type,
    is_docling_path,
)

__all__ = [
    "Ingestor",
    "compute_content_hash",
    "detect_content_type",
    "is_docling_path",
]
