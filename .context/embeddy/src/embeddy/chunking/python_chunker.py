# src/embeddy/chunking/python_chunker.py
"""AST-based Python chunker.

Parses Python source using the ``ast`` module to extract top-level functions,
classes, and module-level code as separate chunks. Falls back to paragraph-style
chunking when the source cannot be parsed.
"""

from __future__ import annotations

import ast
import logging

from embeddy.chunking.base import BaseChunker
from embeddy.models import Chunk, ContentType, IngestResult

logger = logging.getLogger(__name__)


class PythonChunker(BaseChunker):
    """Chunk Python source code using AST parsing.

    Extracts:
    - Top-level functions (chunk_type="function")
    - Top-level classes (chunk_type="class", including full body)
    - Module-level code: imports, constants, docstrings (chunk_type="module")

    Falls back to simple line-based splitting when AST parsing fails
    (e.g. syntax errors).
    """

    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Parse Python source and extract chunks."""
        text = ingest_result.text
        lines = text.splitlines(keepends=True)

        try:
            tree = ast.parse(text)
        except SyntaxError:
            logger.warning(
                "AST parse failed for %s, falling back to paragraph chunking",
                ingest_result.source.file_path,
            )
            return self._fallback_chunk(ingest_result)

        chunks: list[Chunk] = []
        # Track which lines belong to top-level nodes
        node_ranges: list[tuple[int, int, str, str | None]] = []  # (start, end, type, name)

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                start = node.lineno
                end = node.end_lineno or node.lineno
                node_ranges.append((start, end, "function", node.name))
            elif isinstance(node, ast.ClassDef):
                if self.config.python_granularity == "function":
                    # At function granularity, extract methods as separate chunks
                    # but still produce a class chunk for the class body
                    start = node.lineno
                    end = node.end_lineno or node.lineno
                    node_ranges.append((start, end, "class", node.name))
                else:
                    # At class/module granularity, class is one chunk
                    start = node.lineno
                    end = node.end_lineno or node.lineno
                    node_ranges.append((start, end, "class", node.name))

        # Collect module-level lines (lines not covered by any top-level node)
        covered = set()
        for start, end, _, _ in node_ranges:
            for i in range(start, end + 1):
                covered.add(i)

        module_lines = []
        for i, line in enumerate(lines, start=1):
            if i not in covered:
                module_lines.append((i, line))

        # Create module chunk from uncovered lines (if non-empty)
        if module_lines:
            module_text = "".join(line for _, line in module_lines).strip()
            if module_text:
                chunks.append(
                    Chunk(
                        content=module_text,
                        content_type=ContentType.PYTHON,
                        chunk_type="module",
                        source=ingest_result.source,
                        start_line=module_lines[0][0],
                        end_line=module_lines[-1][0],
                        name="<module>",
                    )
                )

        # Create chunks for each top-level node
        for start, end, node_type, name in node_ranges:
            # Extract the text for this node (1-indexed lines)
            node_text = "".join(lines[start - 1 : end]).rstrip()
            if node_text.strip():
                chunks.append(
                    Chunk(
                        content=node_text,
                        content_type=ContentType.PYTHON,
                        chunk_type=node_type,
                        source=ingest_result.source,
                        start_line=start,
                        end_line=end,
                        name=name,
                    )
                )

        # Sort by start_line for consistent ordering
        chunks.sort(key=lambda c: c.start_line or 0)
        return chunks

    def _fallback_chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Fallback: split by double-newlines (paragraph style)."""
        text = ingest_result.text
        paragraphs = text.split("\n\n")
        chunks: list[Chunk] = []

        line_offset = 1
        for para in paragraphs:
            stripped = para.strip()
            if stripped:
                line_count = para.count("\n") + 1
                chunks.append(
                    Chunk(
                        content=stripped,
                        content_type=ingest_result.content_type,
                        chunk_type="paragraph",
                        source=ingest_result.source,
                        start_line=line_offset,
                        end_line=line_offset + line_count - 1,
                    )
                )
            line_offset += para.count("\n") + 2  # +2 for the \n\n separator

        return chunks
