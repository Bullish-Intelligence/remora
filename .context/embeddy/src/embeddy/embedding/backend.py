# src/embeddy/embedding/backend.py
"""Embedding backend implementations.

Defines the abstract ``EmbedderBackend`` interface and two concrete
implementations:

- ``LocalBackend`` — loads a model in-process, runs inference via
  ``asyncio.to_thread()``.
- ``RemoteBackend`` — calls a remote embedding server over HTTP using
  ``httpx.AsyncClient``.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx

from embeddy.exceptions import EncodingError, ModelLoadError
from embeddy.models import EmbedInput

if TYPE_CHECKING:
    from embeddy.config import EmbedderConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EmbedderBackend(ABC):
    """Abstract interface for embedding backends.

    Subclasses must implement :meth:`encode`, :meth:`load`, :meth:`health`,
    and the :attr:`model_name` / :attr:`dimension` properties.
    """

    @abstractmethod
    async def encode(
        self,
        inputs: list[EmbedInput],
        instruction: str | None = None,
    ) -> list[list[float]]:
        """Encode a batch of inputs into raw embedding vectors.

        Args:
            inputs: One or more multimodal inputs to embed.
            instruction: Optional instruction to prepend to each input.

        Returns:
            A list of embedding vectors (each a list of floats).
        """
        ...

    @abstractmethod
    async def load(self) -> None:
        """Load / initialise the backend (e.g. download and load model weights)."""
        ...

    @abstractmethod
    async def health(self) -> bool:
        """Return ``True`` if the backend is healthy and ready to encode."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier of the model served by this backend."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Native (full) vector dimension of the model."""
        ...


# ---------------------------------------------------------------------------
# Local (in-process) backend
# ---------------------------------------------------------------------------


class LocalBackend(EmbedderBackend):
    """Loads a model in-process and runs inference locally.

    All synchronous operations (model loading, encoding) are dispatched
    to the default executor via :func:`asyncio.to_thread` so the event
    loop is never blocked.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        self._config = config
        self._model: object | None = None  # Set by load()

    # -- public interface ---------------------------------------------------

    async def encode(
        self,
        inputs: list[EmbedInput],
        instruction: str | None = None,
    ) -> list[list[float]]:
        if self._model is None:
            raise ModelLoadError("Model not loaded — call load() first")
        return await asyncio.to_thread(self._encode_sync, inputs, instruction)

    async def load(self) -> None:
        try:
            await asyncio.to_thread(self._load_model_sync)
        except ModelLoadError:
            raise
        except Exception as exc:
            raise ModelLoadError(str(exc)) from exc

    async def health(self) -> bool:
        return self._model is not None

    @property
    def model_name(self) -> str:
        return self._config.model_name

    @property
    def dimension(self) -> int:
        return self._config.embedding_dimension

    # -- sync internals (run in thread) -------------------------------------

    def _load_model_sync(self) -> None:  # pragma: no cover — needs real model
        """Synchronously load the Qwen3-VL model.

        This method will be replaced / extended when the actual model
        integration is wired up.  For now it serves as the hook that
        tests can mock.
        """
        raise NotImplementedError("Real model loading not yet implemented")

    def _encode_sync(
        self,
        inputs: list[EmbedInput],
        instruction: str | None = None,
    ) -> list[list[float]]:  # pragma: no cover — needs real model
        """Synchronously encode inputs using the loaded model.

        This method will be replaced / extended when the actual model
        integration is wired up.  For now it serves as the hook that
        tests can mock.
        """
        raise NotImplementedError("Real model encoding not yet implemented")


# ---------------------------------------------------------------------------
# Remote (HTTP client) backend
# ---------------------------------------------------------------------------


class RemoteBackend(EmbedderBackend):
    """Calls a remote embedding server over HTTP.

    The remote server is expected to expose:

    - ``POST /encode`` — accepts ``{"inputs": [...], "instruction": ...}``
      and returns ``{"embeddings": [[...], ...], "dimension": N, "model": "..."}``.
    - ``GET /health`` — returns ``{"status": "ok"}`` when healthy.
    """

    def __init__(self, config: EmbedderConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.remote_url or "",
            timeout=config.remote_timeout,
        )

    # -- public interface ---------------------------------------------------

    async def encode(
        self,
        inputs: list[EmbedInput],
        instruction: str | None = None,
    ) -> list[list[float]]:
        payload: dict = {
            "inputs": [inp.model_dump(exclude_none=True) for inp in inputs],
        }
        if instruction is not None:
            payload["instruction"] = instruction

        try:
            response = await self._client.post("/encode", json=payload)
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise EncodingError(f"Connection error to remote embedder: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise EncodingError(f"Remote embedder returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise EncodingError(f"HTTP error from remote embedder: {exc}") from exc

        data = response.json()
        return data["embeddings"]

    async def load(self) -> None:
        # Remote backend doesn't need local model loading — the server
        # is assumed to have the model loaded already.
        pass

    async def health(self) -> bool:
        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self._config.model_name

    @property
    def dimension(self) -> int:
        return self._config.embedding_dimension
