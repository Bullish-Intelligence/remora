# src/embeddy/embedding/__init__.py
"""Embedding layer — model backends and the public Embedder facade.

Re-exports:
    Embedder: High-level facade for encoding inputs.
    EmbedderBackend: Abstract backend interface.
    LocalBackend: In-process model backend.
    RemoteBackend: HTTP client backend.
"""

from __future__ import annotations

from embeddy.embedding.backend import EmbedderBackend, LocalBackend, RemoteBackend
from embeddy.embedding.embedder import Embedder

__all__ = [
    "Embedder",
    "EmbedderBackend",
    "LocalBackend",
    "RemoteBackend",
]
