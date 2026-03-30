# src/embeddy/chunking/token_window_chunker.py
"""Sliding token window chunker.

Splits text into fixed-size windows (by estimated token count) with
configurable overlap. This is the general-purpose fallback chunker.
"""

from __future__ import annotations

from embeddy.chunking.base import BaseChunker
from embeddy.models import Chunk, IngestResult


class TokenWindowChunker(BaseChunker):
    """Chunk text using a sliding token window.

    Uses ``ChunkConfig.max_tokens`` for window size and
    ``ChunkConfig.overlap_tokens`` for overlap between consecutive windows.
    Token counting is based on whitespace splitting (approximation).
    """

    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Split text into overlapping token windows."""
        text = ingest_result.text
        words = text.split()

        if not words:
            return []

        max_tokens = self.config.max_tokens
        overlap = self.config.overlap_tokens
        step = max(1, max_tokens - overlap)

        chunks: list[Chunk] = []
        i = 0

        while i < len(words):
            window_words = words[i : i + max_tokens]
            window_text = " ".join(window_words)

            if window_text.strip():
                chunks.append(
                    Chunk(
                        content=window_text,
                        content_type=ingest_result.content_type,
                        chunk_type="window",
                        source=ingest_result.source,
                    )
                )

            # If this window consumed all remaining words, stop
            if i + max_tokens >= len(words):
                break

            i += step

        return chunks
