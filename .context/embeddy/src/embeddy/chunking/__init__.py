# src/embeddy/chunking/__init__.py
"""Chunking layer for embeddy.

Provides multiple chunking strategies for splitting documents into
embeddable chunks. Use :func:`get_chunker` to auto-select based on
content type, or instantiate a specific chunker directly.
"""

from __future__ import annotations

from embeddy.chunking.base import BaseChunker
from embeddy.chunking.docling_chunker import DoclingChunker
from embeddy.chunking.markdown_chunker import MarkdownChunker
from embeddy.chunking.paragraph_chunker import ParagraphChunker
from embeddy.chunking.python_chunker import PythonChunker
from embeddy.chunking.token_window_chunker import TokenWindowChunker
from embeddy.config import ChunkConfig
from embeddy.models import ContentType

__all__ = [
    "BaseChunker",
    "PythonChunker",
    "MarkdownChunker",
    "ParagraphChunker",
    "TokenWindowChunker",
    "DoclingChunker",
    "get_chunker",
]


# Map from explicit strategy name to chunker class
_STRATEGY_MAP: dict[str, type[BaseChunker]] = {
    "python": PythonChunker,
    "markdown": MarkdownChunker,
    "paragraph": ParagraphChunker,
    "token_window": TokenWindowChunker,
    "docling": DoclingChunker,
}

# Map from content type to chunker class (for auto mode)
_CONTENT_TYPE_MAP: dict[ContentType, type[BaseChunker]] = {
    ContentType.PYTHON: PythonChunker,
    ContentType.MARKDOWN: MarkdownChunker,
    ContentType.DOCLING: DoclingChunker,
    # All other types fall back to ParagraphChunker
}


def get_chunker(content_type: ContentType, config: ChunkConfig) -> BaseChunker:
    """Select and instantiate the appropriate chunker.

    When ``config.strategy`` is ``"auto"``, the chunker is selected based
    on the ``content_type``. Otherwise, the explicit strategy name is used.

    Args:
        content_type: The content type of the document to chunk.
        config: Chunking configuration.

    Returns:
        An instantiated chunker.
    """
    if config.strategy != "auto":
        chunker_cls = _STRATEGY_MAP.get(config.strategy, ParagraphChunker)
        return chunker_cls(config=config)

    # Auto mode: select based on content type
    chunker_cls = _CONTENT_TYPE_MAP.get(content_type, ParagraphChunker)
    return chunker_cls(config=config)
