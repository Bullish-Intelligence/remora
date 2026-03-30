# src/embeddy/config.py
"""Configuration models for embeddy.

All configuration is managed through Pydantic v2 BaseModels with validators.
Supports loading from YAML/JSON files, environment variables, and programmatic
construction. Environment variables override file values.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from embeddy.exceptions import ValidationError as EmbeddyValidationError

logger = logging.getLogger(__name__)

_BOOL_TRUE_VALUES: set[str] = {"1", "true", "yes", "on"}
_BOOL_FALSE_VALUES: set[str] = {"0", "false", "no", "off"}


def _parse_bool_env(raw: str, env_name: str) -> bool:
    """Parse a boolean value from an environment variable string."""
    lowered = raw.strip().lower()
    if lowered in _BOOL_TRUE_VALUES:
        return True
    if lowered in _BOOL_FALSE_VALUES:
        return False
    raise EmbeddyValidationError(f"Invalid boolean value {raw!r} for environment variable {env_name}.")


# ---------------------------------------------------------------------------
# Embedder config (Qwen3-VL-Embedding-2B)
# ---------------------------------------------------------------------------


class EmbedderConfig(BaseModel):
    """Configuration for the embedding model.

    Targets Qwen3-VL-Embedding-2B by default. Supports multimodal inputs
    (text, images, video) with instruction-aware encoding.

    Supports two backend modes:
    - ``local``: Load the model in-process (requires GPU/torch).
    - ``remote``: Call a dedicated embedding server over HTTP (for
      offloading inference to a remote GPU machine).
    """

    # Backend mode
    mode: str = Field(
        default="local",
        description="Backend mode: 'local' (in-process model) or 'remote' (HTTP client).",
    )
    remote_url: str | None = Field(
        default=None,
        description="URL of the remote embedding server (e.g. 'http://100.x.y.z:8586'). Required when mode='remote'.",
    )
    remote_timeout: float = Field(
        default=120.0,
        description="HTTP timeout in seconds for remote embedding requests.",
    )

    # Model identity
    model_name: str = Field(
        default="Qwen/Qwen3-VL-Embedding-2B",
        description="HuggingFace model identifier or local path.",
    )

    # Local-mode model settings (ignored in remote mode)
    device: str | None = Field(
        default=None,
        description="Device: 'cpu', 'cuda', 'cuda:N', 'mps', or None for auto-detect. Local mode only.",
    )
    torch_dtype: str = Field(
        default="bfloat16",
        description="Torch dtype for model weights: 'float32', 'float16', 'bfloat16'. Local mode only.",
    )
    attn_implementation: str | None = Field(
        default=None,
        description="Attention implementation: None (auto), 'flash_attention_2', 'sdpa', 'eager'. Local mode only.",
    )
    trust_remote_code: bool = Field(
        default=True,
        description="Whether to trust remote code when loading model. Required for Qwen3-VL. Local mode only.",
    )
    cache_dir: str | None = Field(
        default=None,
        description="Directory for model download cache. Local mode only.",
    )

    # Embedding parameters (used in both modes)
    embedding_dimension: int = Field(
        default=2048,
        description="Output embedding dimension. MRL supports 64-2048.",
    )
    max_length: int = Field(
        default=8192,
        description="Max token sequence length for inputs.",
    )
    batch_size: int = Field(
        default=8,
        description="Number of inputs to encode per batch.",
    )
    normalize: bool = Field(
        default=True,
        description="Whether to L2-normalize embedding vectors.",
    )
    document_instruction: str = Field(
        default="Represent the user's input.",
        description="Default instruction prepended to document inputs.",
    )
    query_instruction: str = Field(
        default="Retrieve relevant documents, images, or text for the user's query.",
        description="Default instruction prepended to query inputs.",
    )

    # Image processing
    min_pixels: int = Field(default=4096, description="Minimum pixel count for image inputs.")
    max_pixels: int = Field(default=1843200, description="Maximum pixel count for image inputs (1280x1440).")

    # LRU cache
    lru_cache_size: int = Field(
        default=1024,
        description="Max entries in the embedder's in-memory LRU cache. 0 to disable.",
    )

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        allowed = {"local", "remote"}
        if value not in allowed:
            raise ValueError(f"mode must be one of {sorted(allowed)}, got {value!r}")
        return value

    @field_validator("remote_timeout")
    @classmethod
    def validate_remote_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("remote_timeout must be positive")
        return value

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_name must be a non-empty string")
        return value

    @field_validator("torch_dtype")
    @classmethod
    def validate_torch_dtype(cls, value: str) -> str:
        allowed = {"float32", "float16", "bfloat16"}
        if value not in allowed:
            raise ValueError(f"torch_dtype must be one of {sorted(allowed)}, got {value!r}")
        return value

    @field_validator("attn_implementation")
    @classmethod
    def validate_attn_implementation(cls, value: str | None) -> str | None:
        if value is None:
            return value
        allowed = {"flash_attention_2", "sdpa", "eager"}
        if value not in allowed:
            raise ValueError(f"attn_implementation must be one of {sorted(allowed)} or None, got {value!r}")
        return value

    @field_validator("embedding_dimension")
    @classmethod
    def validate_embedding_dimension(cls, value: int) -> int:
        if value < 1 or value > 2048:
            raise ValueError(f"embedding_dimension must be between 1 and 2048, got {value}")
        return value

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, value: int) -> int:
        if value < 1:
            raise ValueError("batch_size must be at least 1")
        return value

    @field_validator("max_length")
    @classmethod
    def validate_max_length(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_length must be at least 1")
        return value

    @field_validator("lru_cache_size")
    @classmethod
    def validate_lru_cache_size(cls, value: int) -> int:
        if value < 0:
            raise ValueError("lru_cache_size must be non-negative")
        return value

    @model_validator(mode="after")
    def validate_remote_url_required(self) -> EmbedderConfig:
        """When mode is 'remote', remote_url must be set."""
        if self.mode == "remote" and not self.remote_url:
            raise ValueError("remote_url is required when mode='remote'")
        return self

    @classmethod
    def from_env(cls) -> EmbedderConfig:
        """Construct configuration from environment variables.

        All fields can be overridden via EMBEDDY_* environment variables:
            EMBEDDY_EMBEDDER_MODE, EMBEDDY_REMOTE_URL, EMBEDDY_REMOTE_TIMEOUT,
            EMBEDDY_MODEL_NAME, EMBEDDY_DEVICE, EMBEDDY_TORCH_DTYPE,
            EMBEDDY_EMBEDDING_DIMENSION, EMBEDDY_MAX_LENGTH,
            EMBEDDY_BATCH_SIZE, EMBEDDY_NORMALIZE, EMBEDDY_CACHE_DIR,
            EMBEDDY_TRUST_REMOTE_CODE, EMBEDDY_LRU_CACHE_SIZE
        """
        kwargs: dict[str, Any] = {}

        env_mode = os.getenv("EMBEDDY_EMBEDDER_MODE")
        if env_mode is not None:
            kwargs["mode"] = env_mode

        env_remote_url = os.getenv("EMBEDDY_REMOTE_URL")
        if env_remote_url is not None:
            kwargs["remote_url"] = env_remote_url

        env_remote_timeout = os.getenv("EMBEDDY_REMOTE_TIMEOUT")
        if env_remote_timeout is not None:
            try:
                kwargs["remote_timeout"] = float(env_remote_timeout)
            except ValueError as exc:
                raise EmbeddyValidationError(
                    f"Invalid float value {env_remote_timeout!r} for EMBEDDY_REMOTE_TIMEOUT."
                ) from exc

        env_model = os.getenv("EMBEDDY_MODEL_NAME")
        if env_model is not None:
            kwargs["model_name"] = env_model

        env_device = os.getenv("EMBEDDY_DEVICE")
        if env_device is not None:
            kwargs["device"] = env_device

        env_dtype = os.getenv("EMBEDDY_TORCH_DTYPE")
        if env_dtype is not None:
            kwargs["torch_dtype"] = env_dtype

        env_dim = os.getenv("EMBEDDY_EMBEDDING_DIMENSION")
        if env_dim is not None:
            try:
                kwargs["embedding_dimension"] = int(env_dim)
            except ValueError as exc:
                raise EmbeddyValidationError(
                    f"Invalid integer value {env_dim!r} for EMBEDDY_EMBEDDING_DIMENSION."
                ) from exc

        env_max_len = os.getenv("EMBEDDY_MAX_LENGTH")
        if env_max_len is not None:
            try:
                kwargs["max_length"] = int(env_max_len)
            except ValueError as exc:
                raise EmbeddyValidationError(f"Invalid integer value {env_max_len!r} for EMBEDDY_MAX_LENGTH.") from exc

        env_batch = os.getenv("EMBEDDY_BATCH_SIZE")
        if env_batch is not None:
            try:
                kwargs["batch_size"] = int(env_batch)
            except ValueError as exc:
                raise EmbeddyValidationError(f"Invalid integer value {env_batch!r} for EMBEDDY_BATCH_SIZE.") from exc

        env_normalize = os.getenv("EMBEDDY_NORMALIZE")
        if env_normalize is not None:
            kwargs["normalize"] = _parse_bool_env(env_normalize, "EMBEDDY_NORMALIZE")

        env_cache_dir = os.getenv("EMBEDDY_CACHE_DIR")
        if env_cache_dir is not None:
            kwargs["cache_dir"] = env_cache_dir

        env_trust = os.getenv("EMBEDDY_TRUST_REMOTE_CODE")
        if env_trust is not None:
            kwargs["trust_remote_code"] = _parse_bool_env(env_trust, "EMBEDDY_TRUST_REMOTE_CODE")

        env_lru = os.getenv("EMBEDDY_LRU_CACHE_SIZE")
        if env_lru is not None:
            try:
                kwargs["lru_cache_size"] = int(env_lru)
            except ValueError as exc:
                raise EmbeddyValidationError(f"Invalid integer value {env_lru!r} for EMBEDDY_LRU_CACHE_SIZE.") from exc

        try:
            return cls(**kwargs)
        except Exception as exc:
            raise EmbeddyValidationError(f"Invalid Embedder configuration from environment: {exc}") from exc


# ---------------------------------------------------------------------------
# Store config
# ---------------------------------------------------------------------------


class StoreConfig(BaseModel):
    """Configuration for the vector store (sqlite-vec + FTS5)."""

    db_path: str = Field(
        default="embeddy.db",
        description="Path to the SQLite database file.",
    )
    wal_mode: bool = Field(
        default=True,
        description="Enable WAL journal mode for concurrent reads.",
    )

    @field_validator("db_path")
    @classmethod
    def validate_db_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("db_path must be a non-empty string")
        return value


# ---------------------------------------------------------------------------
# Chunk config
# ---------------------------------------------------------------------------


class ChunkConfig(BaseModel):
    """Configuration for document chunking."""

    strategy: str = Field(
        default="auto",
        description="Chunking strategy: 'auto', 'python', 'markdown', 'paragraph', 'token_window', 'docling'.",
    )
    max_tokens: int = Field(default=512, description="Max tokens per chunk.")
    overlap_tokens: int = Field(default=64, description="Token overlap for sliding window strategy.")
    merge_short: bool = Field(default=True, description="Merge paragraphs shorter than min_tokens.")
    min_tokens: int = Field(default=64, description="Minimum chunk size before merging.")
    python_granularity: str = Field(
        default="function",
        description="Python chunking granularity: 'function', 'class', 'module'.",
    )
    markdown_heading_level: int = Field(
        default=2,
        description="Split markdown at this heading level.",
    )

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        allowed = {"auto", "python", "markdown", "paragraph", "token_window", "docling"}
        if value not in allowed:
            raise ValueError(f"strategy must be one of {sorted(allowed)}, got {value!r}")
        return value

    @field_validator("max_tokens")
    @classmethod
    def validate_max_tokens(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_tokens must be at least 1")
        return value

    @field_validator("overlap_tokens")
    @classmethod
    def validate_overlap_tokens(cls, value: int) -> int:
        if value < 0:
            raise ValueError("overlap_tokens must be non-negative")
        return value

    @field_validator("python_granularity")
    @classmethod
    def validate_python_granularity(cls, value: str) -> str:
        allowed = {"function", "class", "module"}
        if value not in allowed:
            raise ValueError(f"python_granularity must be one of {sorted(allowed)}, got {value!r}")
        return value

    @field_validator("markdown_heading_level")
    @classmethod
    def validate_markdown_heading_level(cls, value: int) -> int:
        if value < 1 or value > 6:
            raise ValueError(f"markdown_heading_level must be 1-6, got {value}")
        return value

    @model_validator(mode="after")
    def validate_overlap_less_than_max(self) -> ChunkConfig:
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError(f"overlap_tokens ({self.overlap_tokens}) must be less than max_tokens ({self.max_tokens})")
        return self


# ---------------------------------------------------------------------------
# Pipeline config
# ---------------------------------------------------------------------------


class PipelineConfig(BaseModel):
    """Configuration for the ingest pipeline."""

    collection: str = Field(
        default="default",
        description="Default collection name for ingested content.",
    )
    concurrency: int = Field(
        default=4,
        description="Max concurrent file processing tasks during directory ingest.",
    )
    include_patterns: list[str] = Field(
        default_factory=list,
        description="Glob patterns to include during directory ingest.",
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            ".*",
            "__pycache__",
            "node_modules",
            ".git",
            "*.pyc",
            "*.pyo",
        ],
        description="Glob patterns to exclude during directory ingest.",
    )

    @field_validator("collection")
    @classmethod
    def validate_collection(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("collection name must be non-empty")
        return value

    @field_validator("concurrency")
    @classmethod
    def validate_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("concurrency must be at least 1")
        return value


# ---------------------------------------------------------------------------
# Server config
# ---------------------------------------------------------------------------


class ServerConfig(BaseModel):
    """Configuration for the HTTP server."""

    host: str = Field(default="127.0.0.1", description="Host to bind to.")
    port: int = Field(default=8585, description="Port to bind to.")
    workers: int = Field(default=1, description="Number of uvicorn worker processes.")
    log_level: str = Field(default="info", description="Logging level.")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"],
        description="CORS allowed origins.",
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if value < 1 or value > 65535:
            raise ValueError(f"port must be 1-65535, got {value}")
        return value

    @field_validator("workers")
    @classmethod
    def validate_workers(cls, value: int) -> int:
        if value < 1:
            raise ValueError("workers must be at least 1")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed = {"debug", "info", "warning", "error", "critical"}
        if value.lower() not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return value.lower()


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class EmbeddyConfig(BaseModel):
    """Top-level configuration combining all sub-configs."""

    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


# ---------------------------------------------------------------------------
# Config file loading
# ---------------------------------------------------------------------------


def load_config_file(path: str | None = None) -> EmbeddyConfig:
    """Load configuration from a YAML or JSON file.

    The configuration file uses a nested structure with optional sections:
    ``embedder``, ``store``, ``chunk``, ``pipeline``, ``server``.

    Environment variables override file values for embedder config.

    Args:
        path: Path to the configuration file. Falls back to
            ``EMBEDDY_CONFIG_PATH`` env var if not provided.

    Returns:
        A validated :class:`EmbeddyConfig` instance.
    """
    config_path_str = path or os.getenv("EMBEDDY_CONFIG_PATH")
    if not config_path_str:
        raise EmbeddyValidationError("No configuration path provided and EMBEDDY_CONFIG_PATH is not set.")

    config_path = Path(config_path_str)
    if not config_path.is_file():
        raise FileNotFoundError(str(config_path))

    try:
        raw_text = config_path.read_text()
        if config_path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml
            except ImportError as exc:
                raise EmbeddyValidationError(
                    "PyYAML is required to load YAML config files. Install it with: pip install pyyaml"
                ) from exc
            loaded = yaml.safe_load(raw_text)
        elif config_path.suffix.lower() == ".json":
            loaded = json.loads(raw_text)
        else:
            # Try YAML first, fall back to JSON
            try:
                import yaml

                loaded = yaml.safe_load(raw_text)
            except Exception:
                loaded = json.loads(raw_text)
    except EmbeddyValidationError:
        raise
    except Exception as exc:
        raise EmbeddyValidationError(f"Failed to parse configuration file {config_path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise EmbeddyValidationError("Configuration file must contain a mapping at the top level.")

    try:
        config = EmbeddyConfig(**loaded)
    except Exception as exc:
        raise EmbeddyValidationError(f"Invalid configuration values in {config_path}: {exc}") from exc

    return config
