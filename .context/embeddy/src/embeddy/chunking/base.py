# src/embeddy/chunking/base.py
"""Base chunker abstract class.

All chunkers inherit from BaseChunker and implement the ``chunk`` method.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from embeddy.config import ChunkConfig
from embeddy.models import Chunk, IngestResult


class BaseChunker(ABC):
    """Abstract base class for all document chunkers.

    Args:
        config: Chunking configuration controlling strategy parameters.
    """

    def __init__(self, config: ChunkConfig) -> None:
        self.config = config

    @abstractmethod
    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        """Split an ingested document into chunks suitable for embedding.

        Args:
            ingest_result: The ingested document to chunk.

        Returns:
            A list of :class:`Chunk` objects.
        """
        ...
