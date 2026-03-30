# src/embeddy/store/__init__.py
"""Storage layer for embeddy.

Re-exports the :class:`VectorStore` implementation backed by sqlite-vec + FTS5.
"""

from embeddy.store.vector_store import VectorStore

__all__ = ["VectorStore"]
