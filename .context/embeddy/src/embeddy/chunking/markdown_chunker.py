# src/embeddy/chunking/markdown_chunker.py
"""Heading-boundary markdown chunker.

Splits markdown text at heading boundaries. Each section from one heading
to the next heading of equal or higher level becomes a chunk. Subsections
are included in their parent section's chunk.
"""

from __future__ import annotations

import re

from embeddy.chunking.base import BaseChunker
from embeddy.models import Chunk, ContentType, IngestResult


# Regex to match markdown headings: # through ######
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


class MarkdownChunker(BaseChunker):
    """Chunk markdown text by splitting at heading boundaries.

    Uses ``ChunkConfig.markdown_heading_level`` to control the split level.
    For example, level=2 splits at ``##`` headings (``###`` and deeper are
    kept inside their parent ``##`` section).
    """

    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Split markdown text at heading boundaries."""
        text = ingest_result.text
        split_level = self.config.markdown_heading_level

        # Find all headings at or above the split level
        splits: list[tuple[int, str]] = []  # (char_offset, heading_text)

        for match in _HEADING_RE.finditer(text):
            hashes = match.group(1)
            heading_text = match.group(2).strip()
            level = len(hashes)

            if level <= split_level:
                splits.append((match.start(), heading_text))

        # If no headings found at the split level, return the whole text as one chunk
        if not splits:
            return [
                Chunk(
                    content=text.strip(),
                    content_type=ingest_result.content_type,
                    chunk_type="heading_section",
                    source=ingest_result.source,
                    name=None,
                )
            ]

        chunks: list[Chunk] = []

        # Content before the first heading (preamble)
        if splits[0][0] > 0:
            preamble = text[: splits[0][0]].strip()
            if preamble:
                chunks.append(
                    Chunk(
                        content=preamble,
                        content_type=ingest_result.content_type,
                        chunk_type="heading_section",
                        source=ingest_result.source,
                        name=None,
                    )
                )

        # Each section: from this heading to the next heading at the same level
        for i, (offset, heading_text) in enumerate(splits):
            if i + 1 < len(splits):
                next_offset = splits[i + 1][0]
                section_text = text[offset:next_offset].strip()
            else:
                section_text = text[offset:].strip()

            if section_text:
                chunks.append(
                    Chunk(
                        content=section_text,
                        content_type=ingest_result.content_type,
                        chunk_type="heading_section",
                        source=ingest_result.source,
                        name=heading_text,
                    )
                )

        return chunks
