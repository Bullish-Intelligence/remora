# src/embeddy/chunking/docling_chunker.py
"""Docling bridge chunker.

Bridges to Docling's ``HybridChunker`` for chunking rich documents
(PDF, DOCX, HTML, etc.) that were parsed via Docling's ``DocumentConverter``.
"""

from __future__ import annotations

import logging
from typing import Any

from embeddy.chunking.base import BaseChunker
from embeddy.exceptions import ChunkingError
from embeddy.models import Chunk, ContentType, IngestResult

logger = logging.getLogger(__name__)

try:
    from docling_core.transforms.chunker import HybridChunker
except ImportError:
    HybridChunker = None  # type: ignore[assignment,misc]


class DoclingChunker(BaseChunker):
    """Chunk documents using Docling's HybridChunker.

    Requires that the ``IngestResult.docling_document`` field is populated
    (i.e. the document was parsed via Docling's DocumentConverter).
    """

    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Chunk a Docling document using HybridChunker."""
        if ingest_result.docling_document is None:
            raise ChunkingError(
                "DoclingChunker requires a docling_document on the IngestResult. "
                "Ensure the document was parsed via Docling's DocumentConverter."
            )

        if HybridChunker is None:
            raise ChunkingError("Docling is not installed. Install it with: pip install docling docling-core")

        doc = ingest_result.docling_document

        try:
            hybrid_chunker = HybridChunker(
                max_tokens=self.config.max_tokens,
                merge_peers=True,
            )
            docling_chunks = hybrid_chunker.chunk(doc)
        except Exception as exc:
            raise ChunkingError(f"Docling HybridChunker failed: {exc}") from exc

        chunks: list[Chunk] = []
        for dc in docling_chunks:
            text = dc.text if hasattr(dc, "text") else str(dc)
            if not text or not text.strip():
                continue

            # Extract heading path from metadata if available
            name = None
            metadata: dict[str, Any] = {}
            if hasattr(dc, "meta") and dc.meta is not None:
                if hasattr(dc.meta, "headings") and dc.meta.headings:
                    name = " > ".join(dc.meta.headings)
                    metadata["headings"] = dc.meta.headings
                if hasattr(dc.meta, "origin") and dc.meta.origin is not None:
                    metadata["origin"] = str(dc.meta.origin)

            chunks.append(
                Chunk(
                    content=text,
                    content_type=ContentType.DOCLING,
                    chunk_type="docling",
                    source=ingest_result.source,
                    name=name,
                    metadata=metadata,
                )
            )

        return chunks
