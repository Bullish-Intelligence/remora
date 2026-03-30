# src/embeddy/embedding/embedder.py
"""High-level Embedder facade.

The :class:`Embedder` provides a clean public API for encoding text and
multimodal inputs into embedding vectors.  It delegates to a concrete
:class:`~embeddy.embedding.backend.EmbedderBackend` (local or remote)
and adds:

- Automatic backend selection based on :attr:`EmbedderConfig.mode`.
- Input normalisation (``str`` → :class:`EmbedInput`).
- MRL dimension truncation when ``embedding_dimension < model dimension``.
- L2 normalisation (when ``config.normalize`` is True).
- Single-item LRU caching keyed on ``(input_text, instruction)``.
- Error wrapping — non-embeddy exceptions become :class:`EncodingError`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING

import numpy as np

from embeddy.exceptions import EmbeddyError, EncodingError
from embeddy.models import EmbedInput, Embedding

if TYPE_CHECKING:
    from embeddy.config import EmbedderConfig
    from embeddy.embedding.backend import EmbedderBackend

logger = logging.getLogger(__name__)


def _cache_key(inp: EmbedInput, instruction: str | None) -> str:
    """Compute a deterministic cache key for a single input + instruction."""
    payload = inp.model_dump(exclude_none=True)
    if instruction is not None:
        payload["__instruction__"] = instruction
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class Embedder:
    """Public embedding facade.

    Wraps a backend (:class:`LocalBackend` or :class:`RemoteBackend`) and
    exposes a unified async API for encoding inputs.

    Usage::

        config = EmbedderConfig(mode="local")
        embedder = Embedder(config)
        await embedder._backend.load()  # only needed for local mode

        result = await embedder.encode("hello world")
        query_emb = await embedder.encode_query("search query")
        doc_emb = await embedder.encode_document("document text")
    """

    def __init__(self, config: EmbedderConfig) -> None:
        from embeddy.embedding.backend import LocalBackend, RemoteBackend

        self._config = config

        # Build backend based on mode
        if config.mode == "remote":
            self._backend: EmbedderBackend = RemoteBackend(config)
        else:
            self._backend = LocalBackend(config)

        # LRU cache: OrderedDict preserves insertion order; we use
        # move_to_end() on hits and popitem(last=False) for eviction.
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_max = config.lru_cache_size

    # -- public properties --------------------------------------------------

    @property
    def dimension(self) -> int:
        """Configured output embedding dimension (may differ from model native dim via MRL)."""
        return self._config.embedding_dimension

    @property
    def model_name(self) -> str:
        """Model identifier from config."""
        return self._config.model_name

    # -- public encode methods ----------------------------------------------

    async def encode(
        self,
        inputs: str | EmbedInput | list[str | EmbedInput],
        instruction: str | None = None,
    ) -> list[Embedding]:
        """Encode one or more inputs into :class:`Embedding` objects.

        Args:
            inputs: A single string, :class:`EmbedInput`, or list thereof.
            instruction: Optional instruction prepended to each input.

        Returns:
            A list of :class:`Embedding` instances (one per input).

        Raises:
            EncodingError: On empty input list or backend failure.
        """
        try:
            return await self._encode_impl(inputs, instruction)
        except EmbeddyError:
            raise
        except Exception as exc:
            raise EncodingError(str(exc)) from exc

    async def encode_query(self, text: str) -> Embedding:
        """Encode a search query using the configured query instruction.

        Args:
            text: The query string.

        Returns:
            A single :class:`Embedding`.
        """
        results = await self.encode(text, instruction=self._config.query_instruction)
        return results[0]

    async def encode_document(self, text: str) -> Embedding:
        """Encode a document using the configured document instruction.

        Args:
            text: The document text.

        Returns:
            A single :class:`Embedding`.
        """
        results = await self.encode(text, instruction=self._config.document_instruction)
        return results[0]

    # -- internal implementation --------------------------------------------

    async def _encode_impl(
        self,
        inputs: str | EmbedInput | list[str | EmbedInput],
        instruction: str | None,
    ) -> list[Embedding]:
        """Core encoding logic (no error wrapping)."""
        # Normalise inputs to list[EmbedInput]
        normalised = self._normalise_inputs(inputs)

        if len(normalised) == 0:
            raise EncodingError("Empty input list — nothing to encode")

        # Single-item path: try cache
        if len(normalised) == 1 and self._cache_max > 0:
            key = _cache_key(normalised[0], instruction)
            cached = self._cache_get(key)
            if cached is not None:
                return [self._make_embedding(cached)]

            raw_vectors = await self._backend.encode(normalised, instruction=instruction)
            processed = self._postprocess(raw_vectors)
            self._cache_put(key, processed[0])
            return [self._make_embedding(v) for v in processed]

        # Batch path: bypass cache entirely
        raw_vectors = await self._backend.encode(normalised, instruction=instruction)
        processed = self._postprocess(raw_vectors)
        return [self._make_embedding(v) for v in processed]

    # -- input normalisation ------------------------------------------------

    @staticmethod
    def _normalise_inputs(inputs: str | EmbedInput | list[str | EmbedInput]) -> list[EmbedInput]:
        """Convert mixed inputs to a uniform list of EmbedInput."""
        if isinstance(inputs, str):
            return [EmbedInput(text=inputs)]
        if isinstance(inputs, EmbedInput):
            return [inputs]
        # It's a list
        result: list[EmbedInput] = []
        for item in inputs:
            if isinstance(item, str):
                result.append(EmbedInput(text=item))
            else:
                result.append(item)
        return result

    # -- post-processing (truncation + normalisation) -----------------------

    def _postprocess(self, raw_vectors: list[list[float]]) -> list[list[float]]:
        """Apply MRL truncation and optional L2 normalisation."""
        target_dim = self._config.embedding_dimension
        backend_dim = self._backend.dimension
        truncate = target_dim < backend_dim

        processed: list[list[float]] = []
        for vec in raw_vectors:
            arr = np.array(vec, dtype=np.float32)

            # MRL truncation
            if truncate:
                arr = arr[:target_dim]

            # L2 normalisation
            if self._config.normalize:
                norm = np.linalg.norm(arr)
                if norm > 0:
                    arr = arr / norm

            processed.append(arr.tolist())
        return processed

    def _make_embedding(self, vector: list[float]) -> Embedding:
        """Wrap a processed vector in an Embedding model."""
        return Embedding(
            vector=vector,
            model_name=self._backend.model_name,
            normalized=self._config.normalize,
        )

    # -- LRU cache ----------------------------------------------------------

    def _cache_get(self, key: str) -> list[float] | None:
        """Look up a cache key, returning the vector or None."""
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _cache_put(self, key: str, vector: list[float]) -> None:
        """Insert a vector into the cache, evicting LRU if at capacity."""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = vector
            return
        if len(self._cache) >= self._cache_max:
            self._cache.popitem(last=False)  # evict LRU
        self._cache[key] = vector
