# src/embeddy/chunking/paragraph_chunker.py
"""Double-newline paragraph chunker.

Splits text on paragraph boundaries (double-newline) and optionally merges
short paragraphs together to avoid tiny chunks.
"""

from __future__ import annotations

from embeddy.chunking.base import BaseChunker
from embeddy.models import Chunk, IngestResult


def _estimate_tokens(text: str) -> int:
    """Estimate token count using whitespace splitting.

    This is a rough approximation (~1.3 tokens per word on average).
    Good enough for chunking decisions without requiring a tokenizer.
    """
    return len(text.split())


class ParagraphChunker(BaseChunker):
    """Chunk text by splitting on double-newline (paragraph) boundaries.

    When ``ChunkConfig.merge_short`` is True, consecutive paragraphs shorter
    than ``ChunkConfig.min_tokens`` are merged together.
    """

    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Split text on paragraph boundaries."""
        text = ingest_result.text

        # Split on double-newline
        raw_paragraphs = text.split("\n\n")
        paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]

        if not paragraphs:
            return []

        # Optionally merge short paragraphs
        if self.config.merge_short:
            paragraphs = self._merge_short(paragraphs)

        chunks: list[Chunk] = []
        for para in paragraphs:
            chunks.append(
                Chunk(
                    content=para,
                    content_type=ingest_result.content_type,
                    chunk_type="paragraph",
                    source=ingest_result.source,
                )
            )

        return chunks

    def _merge_short(self, paragraphs: list[str]) -> list[str]:
        """Merge consecutive short paragraphs.

        A paragraph is "short" if its estimated token count is below
        ``self.config.min_tokens``. Short paragraphs are merged with the
        next paragraph until the combined length meets the threshold or
        there are no more paragraphs to merge.
        """
        min_tokens = self.config.min_tokens
        merged: list[str] = []
        buffer = ""

        for para in paragraphs:
            if buffer:
                buffer = buffer + "\n\n" + para
            else:
                buffer = para

            if _estimate_tokens(buffer) >= min_tokens:
                merged.append(buffer)
                buffer = ""

        # Don't lose trailing short content
        if buffer:
            if merged:
                # Merge with the last merged chunk
                merged[-1] = merged[-1] + "\n\n" + buffer
            else:
                merged.append(buffer)

        return merged
