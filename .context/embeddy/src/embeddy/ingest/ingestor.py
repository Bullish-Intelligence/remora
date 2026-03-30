# src/embeddy/ingest/ingestor.py
"""Document ingestion layer.

Accepts file paths or raw text and produces :class:`IngestResult` objects
ready for chunking. Routes rich document formats (PDF, DOCX, etc.) through
Docling's DocumentConverter; reads text/code files directly.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from embeddy.exceptions import IngestError
from embeddy.models import ContentType, IngestResult, SourceMetadata

# Try to import Docling at module level so it can be patched in tests.
# If Docling is not installed, DocumentConverter is set to None and an
# IngestError will be raised at runtime when Docling ingestion is attempted.
try:
    from docling.document_converter import DocumentConverter
except ImportError:
    DocumentConverter = None  # type: ignore[assignment,misc]

# Extension → ContentType mapping for text/code files
_TEXT_EXTENSION_MAP: dict[str, ContentType] = {
    ".py": ContentType.PYTHON,
    ".js": ContentType.JAVASCRIPT,
    ".mjs": ContentType.JAVASCRIPT,
    ".jsx": ContentType.JAVASCRIPT,
    ".ts": ContentType.TYPESCRIPT,
    ".tsx": ContentType.TYPESCRIPT,
    ".rs": ContentType.RUST,
    ".go": ContentType.GO,
    ".c": ContentType.C,
    ".h": ContentType.C,
    ".cpp": ContentType.CPP,
    ".cc": ContentType.CPP,
    ".cxx": ContentType.CPP,
    ".hpp": ContentType.CPP,
    ".java": ContentType.JAVA,
    ".rb": ContentType.RUBY,
    ".sh": ContentType.SHELL,
    ".bash": ContentType.SHELL,
    ".md": ContentType.MARKDOWN,
    ".markdown": ContentType.MARKDOWN,
    ".rst": ContentType.RST,
    ".txt": ContentType.GENERIC,
}

# Extensions that should be routed through Docling
_DOCLING_EXTENSIONS: set[str] = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".tex",
    ".latex",
}


def detect_content_type(file_path: str) -> ContentType:
    """Detect content type from a file path's extension.

    Args:
        file_path: File path (only the extension is examined).

    Returns:
        The detected :class:`ContentType`.
    """
    ext = Path(file_path).suffix.lower()

    # Check Docling extensions first
    if ext in _DOCLING_EXTENSIONS:
        return ContentType.DOCLING

    # Check text/code extensions
    return _TEXT_EXTENSION_MAP.get(ext, ContentType.GENERIC)


def is_docling_path(file_path: str) -> bool:
    """Check whether a file path should be routed through Docling.

    Args:
        file_path: File path to check.

    Returns:
        True if the file should be processed by Docling.
    """
    ext = Path(file_path).suffix.lower()
    return ext in _DOCLING_EXTENSIONS


def compute_content_hash(text: str) -> str:
    """Compute SHA-256 hash of text content.

    Args:
        text: The text to hash.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Ingestor:
    """Async document ingestor.

    Accepts raw text or file paths and produces :class:`IngestResult` objects.
    Text/code files are read directly; rich document formats (PDF, DOCX, etc.)
    are routed through Docling's DocumentConverter.
    """

    async def ingest_text(
        self,
        text: str,
        content_type: ContentType | None = None,
        source: str | None = None,
    ) -> IngestResult:
        """Ingest raw text.

        Args:
            text: The text content to ingest.
            content_type: Explicit content type. Defaults to GENERIC.
            source: Optional source identifier (stored as file_path in metadata).

        Returns:
            An :class:`IngestResult`.

        Raises:
            IngestError: If the text is empty or whitespace-only.
        """
        if not text.strip():
            raise IngestError("Cannot ingest empty or whitespace-only text")

        return IngestResult(
            text=text,
            content_type=content_type or ContentType.GENERIC,
            source=SourceMetadata(
                file_path=source,
                content_hash=compute_content_hash(text),
            ),
        )

    async def ingest_file(
        self,
        path: str | Path,
        content_type: ContentType | None = None,
    ) -> IngestResult:
        """Ingest a file from disk.

        Automatically detects content type from the file extension. Rich
        document formats (PDF, DOCX, images, etc.) are routed through
        Docling's DocumentConverter.

        Args:
            path: Path to the file.
            content_type: Override auto-detected content type.

        Returns:
            An :class:`IngestResult`.

        Raises:
            IngestError: If the file does not exist or cannot be read.
        """
        path = Path(path)

        if not path.exists():
            raise IngestError(f"File not found: {path}")

        if not path.is_file():
            raise IngestError(f"Path is not a file: {path}")

        # Determine content type
        detected_type = content_type or detect_content_type(str(path))

        # Get file stats
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        # Route through Docling or read directly
        if detected_type == ContentType.DOCLING and content_type is None:
            return await self._ingest_docling(path, stat.st_size, modified_at)
        else:
            return await self._ingest_text_file(path, detected_type, stat.st_size, modified_at)

    async def _ingest_text_file(
        self,
        path: Path,
        content_type: ContentType,
        size_bytes: int,
        modified_at: datetime,
    ) -> IngestResult:
        """Read a text/code file directly."""
        try:
            text = await asyncio.to_thread(path.read_text, "utf-8")
        except Exception as exc:
            raise IngestError(f"Failed to read file {path}: {exc}") from exc

        return IngestResult(
            text=text,
            content_type=content_type,
            source=SourceMetadata(
                file_path=str(path),
                size_bytes=size_bytes,
                modified_at=modified_at,
                content_hash=compute_content_hash(text),
            ),
        )

    async def _ingest_docling(
        self,
        path: Path,
        size_bytes: int,
        modified_at: datetime,
    ) -> IngestResult:
        """Route a file through Docling's DocumentConverter."""
        if DocumentConverter is None:
            raise IngestError(
                "Docling is required for ingesting rich documents (PDF, DOCX, etc.) "
                "but is not installed. Install with: pip install docling"
            )

        try:
            conv_result = await asyncio.to_thread(self._run_docling_convert, path)
        except IngestError:
            raise
        except Exception as exc:
            raise IngestError(f"Docling conversion failed for {path}: {exc}") from exc

        doc = conv_result.document
        text = doc.export_to_text()
        content_hash = compute_content_hash(text)

        return IngestResult(
            text=text,
            content_type=ContentType.DOCLING,
            source=SourceMetadata(
                file_path=str(path),
                size_bytes=size_bytes,
                modified_at=modified_at,
                content_hash=content_hash,
            ),
            docling_document=doc,
        )

    @staticmethod
    def _run_docling_convert(path: Path):  # type: ignore[no-untyped-def]
        """Synchronous Docling conversion (runs in thread)."""
        converter = DocumentConverter()
        return converter.convert(str(path))
