# embeddy Technical Specification

**Version**: 0.3.11
**Status**: Implementation complete
**Python**: >= 3.13

## 1. Overview

embeddy is an async-native Python library for multimodal embedding, document chunking, hybrid search, and RAG pipeline orchestration. It provides a complete pipeline from raw documents to searchable vector+fulltext indexes, with both library and client-server deployment modes.

### 1.1 Goals

- Provide a single library covering the full embed-and-search workflow
- Support multimodal inputs (text, image, video) via Qwen3-VL-Embedding-2B
- Offer hybrid search combining vector similarity (KNN) and full-text (BM25)
- Run async-natively without blocking the event loop
- Support both in-process and client-server deployment
- Use SQLite (sqlite-vec + FTS5) for zero-config storage

### 1.2 Non-Goals

- Training or fine-tuning embedding models
- Distributed storage across multiple nodes
- Real-time streaming ingestion

## 2. Package Structure

```
src/embeddy/
├── __init__.py              # Public API, __version__, __all__ (48 exports)
├── models.py                # Core data types (Pydantic v2)
├── config.py                # Configuration models + loader
├── exceptions.py            # Exception hierarchy
├── embedding/
│   ├── backend.py           # EmbedderBackend ABC, LocalBackend, RemoteBackend
│   └── embedder.py          # Embedder facade
├── chunking/
│   ├── base.py              # BaseChunker ABC
│   ├── python_chunker.py    # AST-based Python chunker
│   ├── markdown_chunker.py  # Heading-level Markdown chunker
│   ├── paragraph_chunker.py # Paragraph-based chunker with merging
│   ├── token_window_chunker.py # Fixed-size sliding window
│   ├── docling_chunker.py   # Docling bridge chunker
│   └── __init__.py          # get_chunker() factory
├── store/
│   └── vector_store.py      # VectorStore (sqlite-vec + FTS5)
├── ingest/
│   └── ingestor.py          # Ingestor, content type detection, hashing
├── pipeline/
│   └── pipeline.py          # Pipeline (ingest -> chunk -> embed -> store)
├── search/
│   └── search_service.py    # SearchService (vector, fulltext, hybrid)
├── server/
│   ├── app.py               # create_app() FastAPI factory
│   ├── schemas.py           # Request/response Pydantic models
│   └── routes/              # health, embed, search, ingest, collections, chunks
├── client/
│   └── client.py            # EmbeddyClient (async httpx wrapper)
└── cli/
    └── main.py              # Typer CLI
```

## 3. Data Types

All types are Pydantic v2 `BaseModel` subclasses defined in `embeddy.models`.

### 3.1 Enums

```python
class ContentType(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    GO = "go"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    RUBY = "ruby"
    SHELL = "shell"
    MARKDOWN = "markdown"
    RST = "rst"
    GENERIC = "generic"
    DOCLING = "docling"

class SearchMode(str, Enum):
    VECTOR = "vector"
    FULLTEXT = "fulltext"
    HYBRID = "hybrid"

class FusionStrategy(str, Enum):
    RRF = "rrf"
    WEIGHTED = "weighted"

class DistanceMetric(str, Enum):
    COSINE = "cosine"
    DOT = "dot"
```

### 3.2 Embedding Types

**EmbedInput** — Multimodal input for embedding. At least one of `text`, `image`, or `video` must be provided.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | `str \| None` | `None` | Text content |
| `image` | `str \| None` | `None` | File path, URL, or base64 |
| `video` | `str \| None` | `None` | File path or URL |
| `instruction` | `str \| None` | `None` | Per-input instruction override |

**Embedding** — A single embedding vector with metadata.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `vector` | `list[float] \| np.ndarray` | required | Embedding vector |
| `model_name` | `str` | required | Model identifier |
| `normalized` | `bool` | `True` | Whether L2-normalized |
| `input_type` | `str` | `"text"` | Input modality |

Properties: `dimension -> int`, Methods: `to_list() -> list[float]`

**SimilarityScore** — Numeric similarity between two embeddings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `score` | `float` | required | Similarity value |
| `metric` | `str` | `"cosine"` | `"cosine"` or `"dot"` |

### 3.3 Ingestion Types

**SourceMetadata** — Metadata about the source of ingested content.

| Field | Type | Default |
|-------|------|---------|
| `file_path` | `str \| None` | `None` |
| `url` | `str \| None` | `None` |
| `size_bytes` | `int \| None` | `None` |
| `modified_at` | `datetime \| None` | `None` |
| `content_hash` | `str \| None` | `None` |

**IngestResult** — Result of ingesting a single document.

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` | required |
| `content_type` | `ContentType` | required |
| `source` | `SourceMetadata` | `SourceMetadata()` |
| `docling_document` | `Any \| None` | `None` |

### 3.4 Chunk Types

**Chunk** — A chunk of content ready for embedding.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | `str` | UUID v4 | Unique chunk identifier |
| `content` | `str` | required | Chunk text (cannot be empty) |
| `content_type` | `ContentType` | required | Content type |
| `chunk_type` | `str` | `"generic"` | e.g. function, class, heading_section, paragraph, window |
| `source` | `SourceMetadata` | `SourceMetadata()` | Source metadata |
| `start_line` | `int \| None` | `None` | Start line in source |
| `end_line` | `int \| None` | `None` | End line in source |
| `name` | `str \| None` | `None` | Function/class name, heading text |
| `parent` | `str \| None` | `None` | Parent class, parent heading |
| `metadata` | `dict[str, Any]` | `{}` | Arbitrary metadata |

### 3.5 Collection Types

**Collection** — A named collection of vectors.

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | UUID v4 |
| `name` | `str` | required |
| `dimension` | `int` | required (>= 1) |
| `model_name` | `str` | required |
| `distance_metric` | `DistanceMetric` | `COSINE` |
| `created_at` | `datetime` | `datetime.now()` |
| `metadata` | `dict[str, Any]` | `{}` |

**CollectionStats** — Statistics about a collection.

| Field | Type | Default |
|-------|------|---------|
| `name` | `str` | required |
| `chunk_count` | `int` | `0` |
| `source_count` | `int` | `0` |
| `dimension` | `int` | `0` |
| `model_name` | `str` | `""` |
| `storage_bytes` | `int \| None` | `None` |

### 3.6 Search Types

**SearchFilters** — Pre-filters applied before search.

| Field | Type | Default |
|-------|------|---------|
| `content_types` | `list[ContentType] \| None` | `None` |
| `source_path_prefix` | `str \| None` | `None` |
| `chunk_types` | `list[str] \| None` | `None` |
| `metadata_match` | `dict[str, Any] \| None` | `None` |

**SearchResult** — A single search hit.

| Field | Type | Default |
|-------|------|---------|
| `chunk_id` | `str` | required |
| `content` | `str` | required |
| `score` | `float` | required (must be finite) |
| `source_path` | `str \| None` | `None` |
| `content_type` | `str \| None` | `None` |
| `chunk_type` | `str \| None` | `None` |
| `start_line` | `int \| None` | `None` |
| `end_line` | `int \| None` | `None` |
| `name` | `str \| None` | `None` |
| `metadata` | `dict[str, Any]` | `{}` |

**SearchResults** — Container for search results. Results must be sorted by score descending.

| Field | Type | Default |
|-------|------|---------|
| `results` | `list[SearchResult]` | `[]` |
| `query` | `str` | `""` |
| `collection` | `str` | `""` |
| `mode` | `SearchMode` | `HYBRID` |
| `total_results` | `int` | `0` |
| `elapsed_ms` | `float` | `0.0` |

### 3.7 Pipeline Types

**IngestError** (model) — Error during ingestion of a specific file.

| Field | Type | Default |
|-------|------|---------|
| `file_path` | `str \| None` | `None` |
| `error` | `str` | required |
| `error_type` | `str` | `""` |

**IngestStats** — Statistics from a pipeline ingest operation.

| Field | Type | Default |
|-------|------|---------|
| `files_processed` | `int` | `0` |
| `chunks_created` | `int` | `0` |
| `chunks_embedded` | `int` | `0` |
| `chunks_stored` | `int` | `0` |
| `chunks_skipped` | `int` | `0` |
| `errors` | `list[IngestError]` | `[]` |
| `elapsed_seconds` | `float` | `0.0` |

## 4. Configuration

All config types are Pydantic v2 `BaseModel` subclasses defined in `embeddy.config`.

### 4.1 EmbedderConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `str` | `"local"` | `"local"` or `"remote"` |
| `remote_url` | `str \| None` | `None` | Remote server URL (required when mode=remote) |
| `remote_timeout` | `float` | `120.0` | HTTP timeout for remote requests (seconds) |
| `model_name` | `str` | `"Qwen/Qwen3-VL-Embedding-2B"` | HuggingFace model ID |
| `device` | `str \| None` | `None` | `"cpu"`, `"cuda"`, `"cuda:N"`, `"mps"`, or auto |
| `torch_dtype` | `str` | `"bfloat16"` | `"float32"`, `"float16"`, `"bfloat16"` |
| `attn_implementation` | `str \| None` | `None` | `None`, `"flash_attention_2"`, `"sdpa"`, `"eager"` |
| `trust_remote_code` | `bool` | `True` | Required for Qwen3-VL |
| `cache_dir` | `str \| None` | `None` | Model download cache dir |
| `embedding_dimension` | `int` | `2048` | Output dim, MRL range 1-2048 |
| `max_length` | `int` | `8192` | Max token sequence length |
| `batch_size` | `int` | `8` | Inputs per batch |
| `normalize` | `bool` | `True` | L2-normalize vectors |
| `document_instruction` | `str` | `"Represent the user's input."` | Default document instruction |
| `query_instruction` | `str` | `"Retrieve relevant documents, images, or text for the user's query."` | Default query instruction |
| `min_pixels` | `int` | `4096` | Min pixel count for images |
| `max_pixels` | `int` | `1843200` | Max pixel count for images |
| `lru_cache_size` | `int` | `1024` | LRU cache entries (0 = disabled) |

Environment variables: `EMBEDDY_EMBEDDER_MODE`, `EMBEDDY_REMOTE_URL`, `EMBEDDY_REMOTE_TIMEOUT`, `EMBEDDY_MODEL_NAME`, `EMBEDDY_DEVICE`, `EMBEDDY_TORCH_DTYPE`, `EMBEDDY_EMBEDDING_DIMENSION`, `EMBEDDY_MAX_LENGTH`, `EMBEDDY_BATCH_SIZE`, `EMBEDDY_NORMALIZE`, `EMBEDDY_CACHE_DIR`, `EMBEDDY_TRUST_REMOTE_CODE`, `EMBEDDY_LRU_CACHE_SIZE`.

### 4.2 StoreConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `db_path` | `str` | `"embeddy.db"` | SQLite database path |
| `wal_mode` | `bool` | `True` | Enable WAL journal mode |

### 4.3 ChunkConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | `str` | `"auto"` | `"auto"`, `"python"`, `"markdown"`, `"paragraph"`, `"token_window"`, `"docling"` |
| `max_tokens` | `int` | `512` | Max tokens per chunk |
| `overlap_tokens` | `int` | `64` | Overlap for sliding window (must be < max_tokens) |
| `merge_short` | `bool` | `True` | Merge short paragraphs |
| `min_tokens` | `int` | `64` | Min chunk size before merging |
| `python_granularity` | `str` | `"function"` | `"function"`, `"class"`, `"module"` |
| `markdown_heading_level` | `int` | `2` | Split at this heading level (1-6) |

### 4.4 PipelineConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `collection` | `str` | `"default"` | Default collection name |
| `concurrency` | `int` | `4` | Max concurrent file processing |
| `include_patterns` | `list[str]` | `[]` | Glob include patterns |
| `exclude_patterns` | `list[str]` | `[".*", "__pycache__", "node_modules", ".git", "*.pyc", "*.pyo"]` | Glob exclude patterns |

### 4.5 ServerConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Bind host |
| `port` | `int` | `8585` | Bind port (1-65535) |
| `workers` | `int` | `1` | Uvicorn worker processes |
| `log_level` | `str` | `"info"` | Logging level |
| `cors_origins` | `list[str]` | `["*"]` | CORS allowed origins |

### 4.6 EmbeddyConfig (Top-level)

Composes all sub-configs:

| Field | Type | Default |
|-------|------|---------|
| `embedder` | `EmbedderConfig` | `EmbedderConfig()` |
| `store` | `StoreConfig` | `StoreConfig()` |
| `chunk` | `ChunkConfig` | `ChunkConfig()` |
| `pipeline` | `PipelineConfig` | `PipelineConfig()` |
| `server` | `ServerConfig` | `ServerConfig()` |

### 4.7 Config Loading

```python
from embeddy import load_config_file

# From explicit path
config = load_config_file("embeddy.yaml")

# From EMBEDDY_CONFIG_PATH env var
config = load_config_file()
```

Supports YAML (requires `pyyaml`) and JSON. The file uses nested sections matching the sub-config names: `embedder`, `store`, `chunk`, `pipeline`, `server`.

## 5. Exception Hierarchy

All exceptions inherit from `EmbeddyError`:

```
EmbeddyError
├── ModelLoadError      # Model fails to load (bad path, OOM, etc.)
├── EncodingError       # Encoding inputs fails
├── ValidationError     # Domain-level validation (distinct from pydantic.ValidationError)
├── SearchError         # Search operation fails
├── IngestError         # Document ingestion fails
├── StoreError          # Vector store operation fails
├── ChunkingError       # Document chunking fails
└── ServerError         # HTTP server error
```

## 6. Component APIs

### 6.1 Embedder

```python
class Embedder:
    def __init__(self, config: EmbedderConfig) -> None: ...

    @property
    def dimension(self) -> int: ...
    @property
    def model_name(self) -> str: ...

    async def encode(
        self,
        inputs: str | EmbedInput | list[str | EmbedInput],
        instruction: str | None = None,
    ) -> list[Embedding]: ...

    async def encode_query(self, text: str) -> Embedding: ...
    async def encode_document(self, text: str) -> Embedding: ...
```

- Automatically selects `LocalBackend` or `RemoteBackend` based on `config.mode`
- Normalizes `str` inputs to `EmbedInput(text=...)`
- Applies MRL truncation when `embedding_dimension < model dimension`
- L2 normalizes when `config.normalize=True`
- LRU cache keyed on `(input, instruction)` SHA-256 hash

### 6.2 VectorStore

```python
class VectorStore:
    def __init__(self, config: StoreConfig) -> None: ...

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    # Collection CRUD
    async def create_collection(name, dimension, model_name, distance_metric=COSINE) -> Collection: ...
    async def get_collection(name) -> Collection | None: ...
    async def list_collections() -> list[Collection]: ...
    async def delete_collection(name) -> None: ...

    # Chunk CRUD
    async def add(collection_name, chunks: list[Chunk], embeddings: list[Embedding]) -> None: ...
    async def get(collection_name, chunk_id) -> dict | None: ...
    async def delete(collection_name, chunk_ids: list[str]) -> None: ...
    async def delete_by_source(collection_name, source_path) -> int: ...

    # Search
    async def search_knn(collection_name, query_vector, top_k=10, filters=None) -> list[dict]: ...
    async def search_fts(collection_name, query_text, top_k=10, filters=None) -> list[dict]: ...

    # Stats
    async def count(collection_name) -> int: ...
    async def list_sources(collection_name) -> list[str]: ...
    async def stats(collection_name) -> CollectionStats: ...
    async def has_content_hash(collection_name, content_hash) -> bool: ...
```

Storage schema:
- `collections` — namespace table
- `chunks` — chunk metadata with indexes on (collection_id), (collection_id, source_path), (content_hash), (collection_id, content_type)
- `vec_chunks_{collection_id}` — per-collection sqlite-vec virtual table
- `fts_chunks_{collection_id}` — per-collection FTS5 virtual table (porter + unicode61 tokenizer)

### 6.3 Pipeline

```python
class Pipeline:
    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        collection: str = "default",
        chunk_config: ChunkConfig | None = None,
    ) -> None: ...

    async def ingest_text(text, content_type=None, source=None) -> IngestStats: ...
    async def ingest_file(path, content_type=None) -> IngestStats: ...
    async def ingest_directory(path, include=None, exclude=None, recursive=True) -> IngestStats: ...
    async def reindex_file(path) -> IngestStats: ...
    async def delete_source(source_path) -> int: ...
```

- Auto-creates target collection if missing
- Content-hash deduplication on `ingest_file`
- `get_chunker()` auto-selects chunker by content type (when strategy="auto")
- `reindex_file` deletes old chunks before re-ingesting (bypasses dedup)

### 6.4 SearchService

```python
class SearchService:
    def __init__(self, embedder: Embedder, store: VectorStore) -> None: ...

    async def search(
        query, collection, top_k=10, mode=HYBRID,
        filters=None, min_score=None, hybrid_alpha=0.7, fusion=RRF,
    ) -> SearchResults: ...

    async def search_vector(query, collection, top_k=10, filters=None, min_score=None) -> SearchResults: ...
    async def search_fulltext(query, collection, top_k=10, filters=None, min_score=None) -> SearchResults: ...
    async def find_similar(chunk_id, collection, top_k=10, exclude_self=True) -> SearchResults: ...
```

Hybrid search:
- Over-fetches `top_k * 3` from both backends
- **RRF**: `score(d) = sum(1 / (60 + rank_i(d)))` for each method
- **Weighted**: min-max normalize, then `alpha * vector + (1-alpha) * bm25`

### 6.5 Chunking

Factory: `get_chunker(content_type: ContentType, config: ChunkConfig) -> BaseChunker`

Auto-selection map:
- `PYTHON` → `PythonChunker` (AST-based)
- `MARKDOWN` → `MarkdownChunker` (heading-level splits)
- `DOCLING` → `DoclingChunker` (Docling bridge)
- All others → `ParagraphChunker`

### 6.6 Ingestor

```python
class Ingestor:
    async def ingest_text(text, content_type=None, source=None) -> IngestResult: ...
    async def ingest_file(path, content_type=None) -> IngestResult: ...
```

Utility functions:
- `detect_content_type(file_path) -> ContentType` — extension-based detection
- `is_docling_path(file_path) -> bool` — checks if file needs Docling processing
- `compute_content_hash(text) -> str` — SHA-256 hex digest

Docling-routed extensions: `.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.tex`, `.latex`

### 6.7 EmbeddyClient

```python
class EmbeddyClient:
    def __init__(self, base_url="http://localhost:8585", *, timeout=30.0, transport=None) -> None: ...

    async def __aenter__(self) -> EmbeddyClient: ...
    async def __aexit__(self, *exc) -> None: ...
    async def close(self) -> None: ...

    # All methods return dict[str, Any]
    async def health() -> dict: ...
    async def info() -> dict: ...
    async def embed(texts, *, instruction=None) -> dict: ...
    async def embed_query(text, *, instruction=None) -> dict: ...
    async def search(query, collection="default", *, top_k=10, mode="hybrid", ...) -> dict: ...
    async def find_similar(chunk_id, collection="default", *, top_k=10, exclude_self=True) -> dict: ...
    async def ingest_text(text, collection="default", *, source=None, content_type=None) -> dict: ...
    async def ingest_file(path, collection="default", *, content_type=None) -> dict: ...
    async def ingest_directory(path, collection="default", *, include=None, exclude=None, recursive=True) -> dict: ...
    async def reindex(path, collection="default") -> dict: ...
    async def delete_source(source_path, collection="default") -> dict: ...
    async def list_collections() -> dict: ...
    async def create_collection(name, *, metadata=None) -> dict: ...
    async def get_collection(name) -> dict: ...
    async def delete_collection(name) -> dict: ...
    async def collection_sources(name) -> dict: ...
    async def collection_stats(name) -> dict: ...
    async def get_chunk(chunk_id, *, collection="default") -> dict: ...
    async def delete_chunk(chunk_id, *, collection="default") -> dict: ...
```

## 7. REST API

Base path: `/api/v1`

### 7.1 Health & Info

| Method | Path | Response |
|--------|------|----------|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/info` | `{"version": "0.3.11", "model": "...", "dimension": 2048}` |

### 7.2 Embed

**POST /embed** — Batch embed.

Request:
```json
{
  "inputs": [{"text": "hello"}, {"text": "world"}],
  "instruction": "optional instruction"
}
```

Response:
```json
{
  "embeddings": [[0.1, 0.2, ...], [0.3, 0.4, ...]],
  "dimension": 2048,
  "model": "Qwen/Qwen3-VL-Embedding-2B",
  "elapsed_ms": 42.5
}
```

**POST /embed/query** — Single query embed.

Request: `{"input": {"text": "search query"}, "instruction": "optional"}`
Response: `{"embedding": [0.1, 0.2, ...], "dimension": 2048, "model": "...", "elapsed_ms": 12.3}`

### 7.3 Search

**POST /search**

Request:
```json
{
  "query": "how does auth work?",
  "collection": "code",
  "top_k": 10,
  "mode": "hybrid",
  "filters": {"content_types": ["python"], "source_path_prefix": "src/"},
  "min_score": 0.5,
  "hybrid_alpha": 0.7,
  "fusion": "rrf"
}
```

Response:
```json
{
  "results": [
    {
      "chunk_id": "uuid",
      "content": "...",
      "score": 0.032,
      "source_path": "src/auth.py",
      "content_type": "python",
      "chunk_type": "function",
      "start_line": 42,
      "end_line": 67,
      "name": "authenticate_user",
      "metadata": {}
    }
  ],
  "query": "how does auth work?",
  "collection": "code",
  "mode": "hybrid",
  "total_results": 10,
  "elapsed_ms": 85.2
}
```

**POST /search/similar**

Request: `{"chunk_id": "uuid", "collection": "code", "top_k": 5, "exclude_self": true}`

### 7.4 Ingest

**POST /ingest/text** — `{"text": "...", "collection": "default", "source": "optional", "content_type": "python"}`
**POST /ingest/file** — `{"path": "/abs/path", "collection": "default", "content_type": "python"}`
**POST /ingest/directory** — `{"path": "/abs/dir", "collection": "default", "include": ["*.py"], "exclude": ["*.pyc"], "recursive": true}`
**POST /ingest/reindex** — `{"path": "/abs/path", "collection": "default"}`
**DELETE /ingest/source** — `{"source_path": "/abs/path", "collection": "default"}`

All ingest endpoints return `IngestStats` as JSON.

### 7.5 Collections

| Method | Path | Request Body | Response |
|--------|------|-------------|----------|
| GET | `/collections` | — | `{"collections": [...]}` |
| POST | `/collections` | `{"name": "code", "metadata": {}}` | Collection info (201) |
| GET | `/collections/{name}` | — | Collection info (404 if missing) |
| DELETE | `/collections/{name}` | — | Confirmation (404 if missing) |
| GET | `/collections/{name}/sources` | — | `{"sources": [...]}` |
| GET | `/collections/{name}/stats` | — | `CollectionStats` as JSON |

### 7.6 Chunks

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/chunks/{id}` | `collection=default` | Chunk data (404 if missing) |
| DELETE | `/chunks/{id}` | `collection=default` | Confirmation |

### 7.7 Error Responses

All errors return:
```json
{"error": "error_type", "message": "human-readable description"}
```

Error type mapping:
- `ValidationError` → 400
- `ModelLoadError`, `EncodingError`, `SearchError`, `IngestError`, `StoreError`, `ChunkingError` → 500

## 8. Dependencies

### Core
- `pydantic>=2.0`
- `numpy>=1.24`
- `transformers>=4.57.0`
- `torch>=2.8.0`
- `qwen-vl-utils>=0.0.14`
- `sqlite-vec>=0.1`
- `docling>=2.0`, `docling-core>=2.0`
- `aiofiles>=24.0`

### Optional
- **server**: `fastapi>=0.110`, `uvicorn[standard]>=0.29`
- **cli**: `typer>=0.12`
- **bench**: `pytest-benchmark>=4.0`, `psutil>=5.9`, `pynvml>=11.5`
- **dev**: `pytest>=7.0`, `pytest-asyncio>=0.23`, `pytest-cov>=4.1`, `httpx>=0.27`, `mypy>=1.10`, `ruff>=0.5.0`, `pyyaml>=6.0`

## 9. CLI Reference

```
embeddy --version               Show version
embeddy info                    Show version + default config
embeddy serve [OPTIONS]         Start HTTP server
  --config, -c PATH             Config file
  --host, -h TEXT               Bind host
  --port, -p INT                Bind port
  --db PATH                     SQLite database path
  --log-level, -l TEXT          Log level

embeddy ingest text TEXT        Ingest raw text
  --collection, -C TEXT         Target collection [default: default]
  --source, -s TEXT             Source identifier
  --config, -c PATH             Config file
  --db PATH                     Database path
  --json                        Output as JSON

embeddy ingest file PATH        Ingest a file
  --collection, -C TEXT         Target collection
  --config, -c PATH             Config file
  --db PATH                     Database path
  --json                        Output as JSON

embeddy ingest dir PATH         Ingest a directory
  --collection, -C TEXT         Target collection
  --include, -i TEXT            Include glob pattern
  --exclude, -e TEXT            Exclude glob pattern
  --recursive/--no-recursive    Recurse subdirectories [default: true]
  --config, -c PATH             Config file
  --db PATH                     Database path
  --json                        Output as JSON

embeddy search QUERY            Search a collection
  --collection, -C TEXT         Collection [default: default]
  --top-k, -k INT               Number of results [default: 10]
  --mode, -m TEXT               Search mode: vector|fulltext|hybrid [default: hybrid]
  --min-score FLOAT             Minimum score threshold
  --config, -c PATH             Config file
  --db PATH                     Database path
  --json                        Output as JSON
```
