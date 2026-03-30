# Integration Reference

The one-stop-shop reference for integrating embeddy into your projects. Covers installation, both deployment modes, complete API surfaces (Pipeline, SearchService, EmbeddyClient, REST API), all data types, configuration, error handling, and real-world usage patterns.

## Table of Contents

- [Installation](#installation)
- [Deployment Modes](#deployment-modes)
  - [Library Mode (In-Process)](#library-mode-in-process)
  - [Server Mode (Client-Server)](#server-mode-client-server)
- [Pipeline API](#pipeline-api)
  - [Constructor](#pipeline-constructor)
  - [ingest_text()](#ingest_text)
  - [ingest_file()](#ingest_file)
  - [ingest_directory()](#ingest_directory)
  - [reindex_file()](#reindex_file)
  - [delete_source()](#delete_source)
- [SearchService API](#searchservice-api)
  - [Constructor](#searchservice-constructor)
  - [search()](#search)
  - [search_vector()](#search_vector)
  - [search_fulltext()](#search_fulltext)
  - [find_similar()](#find_similar)
- [Embedder API](#embedder-api)
  - [Constructor](#embedder-constructor)
  - [encode()](#encode)
  - [encode_query()](#encode_query)
  - [encode_document()](#encode_document)
- [VectorStore API](#vectorstore-api)
- [EmbeddyClient API](#embeddyclient-api)
  - [Constructor](#client-constructor)
  - [Health and Info](#health-and-info)
  - [Embedding](#embedding)
  - [Search](#client-search)
  - [Ingestion](#client-ingestion)
  - [Collections](#client-collections)
  - [Chunks](#client-chunks)
- [REST API Reference](#rest-api-reference)
  - [Health and Info Endpoints](#health-and-info-endpoints)
  - [Embedding Endpoints](#embedding-endpoints)
  - [Search Endpoints](#search-endpoints)
  - [Ingestion Endpoints](#ingestion-endpoints)
  - [Collection Endpoints](#collection-endpoints)
  - [Chunk Endpoints](#chunk-endpoints)
  - [Error Responses](#error-responses)
- [Data Types](#data-types)
  - [Enums](#enums)
  - [Embedding Types](#embedding-types)
  - [Ingestion Types](#ingestion-types)
  - [Chunk Types](#chunk-types)
  - [Collection Types](#collection-types)
  - [Search Types](#search-types)
  - [Pipeline Types](#pipeline-types)
- [Configuration Reference](#configuration-reference)
  - [EmbedderConfig](#embedderconfig)
  - [StoreConfig](#storeconfig)
  - [ChunkConfig](#chunkconfig)
  - [PipelineConfig](#pipelineconfig)
  - [ServerConfig](#serverconfig)
  - [Config File Format](#config-file-format)
  - [Environment Variables](#environment-variables)
- [Exceptions](#exceptions)
- [Content Type Detection](#content-type-detection)
  - [Text File Extensions](#text-file-extensions)
  - [Docling Document Formats](#docling-document-formats)
- [Chunking Strategies](#chunking-strategies)
- [Hybrid Search Details](#hybrid-search-details)
- [Usage Patterns](#usage-patterns)
  - [RAG Pipeline](#rag-pipeline)
  - [Code Search](#code-search)
  - [Document Search](#document-search)
  - [Incremental Ingestion](#incremental-ingestion)

---

## Installation

```bash
# Core library only (embedding, chunking, storage, search, pipeline)
pip install embeddy

# With HTTP server (FastAPI + uvicorn)
pip install embeddy[server]

# With CLI (Typer)
pip install embeddy[cli]

# Server + CLI
pip install embeddy[server,cli]

# Everything (server + CLI + benchmarks + dev tools)
pip install embeddy[all]
```

**Python 3.13+ required.**

Core dependencies: `pydantic>=2.0`, `numpy>=1.24`, `transformers>=4.57.0`, `torch>=2.8.0`, `qwen-vl-utils>=0.0.14`, `sqlite-vec>=0.1`, `docling>=2.0`, `docling-core>=2.0`, `aiofiles>=24.0`.

## Deployment Modes

### Library Mode (In-Process)

Everything runs in a single Python process. Best for applications running on a GPU machine.

```python
import asyncio
from embeddy import Embedder, VectorStore, Pipeline, SearchService
from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig

async def main():
    # 1. Create components
    embedder = Embedder(EmbedderConfig(mode="local"))
    store = VectorStore(StoreConfig(db_path="my_vectors.db"))
    await store.initialize()

    # 2. Build pipeline and search service
    pipeline = Pipeline(
        embedder=embedder,
        store=store,
        collection="my_collection",
        chunk_config=ChunkConfig(max_tokens=512),
    )
    search = SearchService(embedder=embedder, store=store)

    # 3. Ingest content
    stats = await pipeline.ingest_directory("./docs", include=["*.md", "*.py"])
    print(f"Ingested {stats.chunks_stored} chunks from {stats.files_processed} files")

    # 4. Search
    results = await search.search("how does authentication work", collection="my_collection")
    for r in results.results:
        print(f"  [{r.score:.4f}] {r.source_path}: {r.content[:100]}...")

asyncio.run(main())
```

### Server Mode (Client-Server)

The entire application runs on a GPU machine. Client machines connect via HTTP using `EmbeddyClient`.

**GPU machine** (runs the server):

```bash
pip install embeddy[server,cli]
embeddy serve --host 0.0.0.0 --port 8585
```

Or programmatically:

```python
from embeddy import Embedder, VectorStore, Pipeline, SearchService
from embeddy.config import EmbedderConfig, StoreConfig
from embeddy.server import create_app
import uvicorn

embedder = Embedder(EmbedderConfig(mode="local"))
store = VectorStore(StoreConfig(db_path="vectors.db"))

import asyncio
asyncio.run(store.initialize())

pipeline = Pipeline(embedder=embedder, store=store)
search = SearchService(embedder=embedder, store=store)

app = create_app(
    embedder=embedder,
    store=store,
    pipeline=pipeline,
    search_service=search,
)

uvicorn.run(app, host="0.0.0.0", port=8585)
```

**Client machine** (lightweight, no GPU needed):

```python
import asyncio
from embeddy import EmbeddyClient

async def main():
    async with EmbeddyClient("http://gpu-machine:8585") as client:
        # Ingest
        stats = await client.ingest_directory("/data/docs", collection="docs")
        print(f"Ingested: {stats}")

        # Search
        results = await client.search("deployment guide", collection="docs")
        for hit in results["results"]:
            print(f"  [{hit['score']:.4f}] {hit['source_path']}")

asyncio.run(main())
```

The client machine only needs `httpx` installed. No GPU, no torch, no model weights.

---

## Pipeline API

The `Pipeline` orchestrates the full ingest flow: Ingestor -> Chunker -> Embedder -> VectorStore.

### Pipeline Constructor

```python
Pipeline(
    embedder: Embedder,
    store: VectorStore,
    collection: str = "default",
    chunk_config: ChunkConfig | None = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `embedder` | `Embedder` | required | The embedding model facade |
| `store` | `VectorStore` | required | The vector store |
| `collection` | `str` | `"default"` | Target collection name (auto-created if missing) |
| `chunk_config` | `ChunkConfig \| None` | `None` | Chunking config override (defaults to `ChunkConfig()`) |

### ingest_text()

```python
async def ingest_text(
    text: str,
    content_type: ContentType | None = None,
    source: str | None = None,
) -> IngestStats
```

Ingest raw text through the full pipeline.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | `str` | required | Text content to ingest |
| `content_type` | `ContentType \| None` | `None` | Explicit content type (defaults to GENERIC) |
| `source` | `str \| None` | `None` | Optional source identifier |

**Returns:** `IngestStats`

```python
stats = await pipeline.ingest_text(
    "def hello(): return 'world'",
    content_type=ContentType.PYTHON,
    source="snippet.py",
)
```

### ingest_file()

```python
async def ingest_file(
    path: str | Path,
    content_type: ContentType | None = None,
) -> IngestStats
```

Ingest a file. Content type is auto-detected from extension. Supports content-hash deduplication — if the file's content hash already exists in the collection, the file is skipped.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | required | Path to the file |
| `content_type` | `ContentType \| None` | `None` | Override auto-detected content type |

**Returns:** `IngestStats` — check `chunks_skipped` for dedup hits.

```python
stats = await pipeline.ingest_file("./src/auth.py")
if stats.chunks_skipped:
    print("File unchanged, skipped")
```

### ingest_directory()

```python
async def ingest_directory(
    path: str | Path,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    recursive: bool = True,
) -> IngestStats
```

Ingest all matching files in a directory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str \| Path` | required | Directory path |
| `include` | `list[str] \| None` | `None` | Glob patterns to include (e.g. `["*.py", "*.md"]`) |
| `exclude` | `list[str] \| None` | `None` | Glob patterns to exclude |
| `recursive` | `bool` | `True` | Recurse into subdirectories |

**Returns:** `IngestStats` — aggregated across all files.

```python
stats = await pipeline.ingest_directory(
    "./src",
    include=["*.py"],
    exclude=["*_test.py"],
    recursive=True,
)
print(f"{stats.files_processed} files, {stats.chunks_stored} chunks, {len(stats.errors)} errors")
```

### reindex_file()

```python
async def reindex_file(path: str | Path) -> IngestStats
```

Delete existing chunks for a file, then re-ingest it. Bypasses content-hash deduplication.

```python
stats = await pipeline.reindex_file("./src/auth.py")
```

### delete_source()

```python
async def delete_source(source_path: str) -> int
```

Delete all chunks from a given source path. Returns the number of chunks deleted.

```python
deleted = await pipeline.delete_source("./old_file.py")
print(f"Removed {deleted} chunks")
```

---

## SearchService API

### SearchService Constructor

```python
SearchService(
    embedder: Embedder,
    store: VectorStore,
)
```

### search()

```python
async def search(
    query: str,
    collection: str,
    top_k: int = 10,
    mode: SearchMode = SearchMode.HYBRID,
    filters: SearchFilters | None = None,
    min_score: float | None = None,
    hybrid_alpha: float = 0.7,
    fusion: FusionStrategy = FusionStrategy.RRF,
) -> SearchResults
```

Main search entry point. Dispatches to vector, fulltext, or hybrid depending on `mode`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | required | Search query text |
| `collection` | `str` | required | Target collection name |
| `top_k` | `int` | `10` | Maximum results to return |
| `mode` | `SearchMode` | `HYBRID` | Search mode: VECTOR, FULLTEXT, or HYBRID |
| `filters` | `SearchFilters \| None` | `None` | Pre-filters (content types, source path prefix, etc.) |
| `min_score` | `float \| None` | `None` | Minimum score threshold |
| `hybrid_alpha` | `float` | `0.7` | Vector vs BM25 weight for weighted fusion (0.0=BM25, 1.0=vector) |
| `fusion` | `FusionStrategy` | `RRF` | Fusion strategy for hybrid mode |

**Returns:** `SearchResults`

```python
from embeddy.models import SearchMode, FusionStrategy, SearchFilters, ContentType

# Hybrid search (default)
results = await search.search("authentication", "my_collection")

# Vector-only with filters
results = await search.search(
    "error handling patterns",
    "codebase",
    mode=SearchMode.VECTOR,
    filters=SearchFilters(content_types=[ContentType.PYTHON]),
    top_k=5,
)

# Hybrid with weighted fusion
results = await search.search(
    "database timeout",
    "docs",
    mode=SearchMode.HYBRID,
    fusion=FusionStrategy.WEIGHTED,
    hybrid_alpha=0.8,  # 80% vector, 20% BM25
)
```

### search_vector()

```python
async def search_vector(
    query: str,
    collection: str,
    top_k: int = 10,
    filters: SearchFilters | None = None,
    min_score: float | None = None,
) -> SearchResults
```

Pure vector/semantic search. Encodes the query, then performs KNN over the vector index.

### search_fulltext()

```python
async def search_fulltext(
    query: str,
    collection: str,
    top_k: int = 10,
    filters: SearchFilters | None = None,
    min_score: float | None = None,
) -> SearchResults
```

Pure full-text (BM25) search via FTS5. No embedding required.

### find_similar()

```python
async def find_similar(
    chunk_id: str,
    collection: str,
    top_k: int = 10,
    exclude_self: bool = True,
) -> SearchResults
```

Find chunks similar to an existing chunk by its ID. Retrieves the chunk, embeds its content, and performs KNN.

```python
results = await search.find_similar("abc-123-def", "my_collection", top_k=5)
```

---

## Embedder API

### Embedder Constructor

```python
Embedder(config: EmbedderConfig)
```

Creates the embedder with automatic backend selection based on `config.mode`:
- `mode="local"` -> `LocalBackend` (in-process model, requires GPU + torch)
- `mode="remote"` -> `RemoteBackend` (HTTP client to remote embedding server)

Properties:
- `embedder.dimension -> int` — configured output dimension
- `embedder.model_name -> str` — model identifier from config

### encode()

```python
async def encode(
    inputs: str | EmbedInput | list[str | EmbedInput],
    instruction: str | None = None,
) -> list[Embedding]
```

Encode one or more inputs. Accepts plain strings (converted to `EmbedInput(text=...)` internally), `EmbedInput` objects, or mixed lists.

Single-item calls use the LRU cache. Batch calls bypass the cache.

```python
# Single string
embeddings = await embedder.encode("hello world")

# Multiple strings
embeddings = await embedder.encode(["hello", "world"])

# Multimodal input
from embeddy.models import EmbedInput
embeddings = await embedder.encode(EmbedInput(text="cat", image="/path/to/cat.jpg"))

# With custom instruction
embeddings = await embedder.encode("query text", instruction="Find similar documents")
```

### encode_query()

```python
async def encode_query(text: str) -> Embedding
```

Encode a search query using the configured `query_instruction` (default: "Retrieve relevant documents, images, or text for the user's query.").

### encode_document()

```python
async def encode_document(text: str) -> Embedding
```

Encode a document using the configured `document_instruction` (default: "Represent the user's input.").

---

## VectorStore API

`VectorStore` manages the SQLite database with sqlite-vec (KNN) and FTS5 (BM25) extensions.

```python
from embeddy import VectorStore
from embeddy.config import StoreConfig

store = VectorStore(StoreConfig(db_path="my.db"))
await store.initialize()  # Creates tables, enables WAL mode
```

Key methods (used internally by Pipeline and SearchService):

| Method | Description |
|--------|-------------|
| `initialize()` | Create schema, load extensions, enable WAL |
| `create_collection(name, dimension, model_name)` | Create a new collection with virtual tables |
| `get_collection(name)` | Get collection metadata (or None) |
| `delete_collection(name)` | Delete collection and all its data |
| `add(collection, chunks, embeddings)` | Insert chunks + embeddings |
| `get(collection, chunk_id)` | Get a single chunk by ID |
| `delete(collection, chunk_id)` | Delete a single chunk |
| `delete_by_source(collection, source_path)` | Delete all chunks from a source |
| `search_knn(collection_name, query_vector, top_k, filters)` | KNN vector search |
| `search_fts(collection_name, query_text, top_k, filters)` | FTS5 full-text search |
| `has_content_hash(collection, content_hash)` | Check if hash exists (for dedup) |
| `list_sources(collection)` | List distinct source paths |
| `collection_stats(name)` | Get collection statistics |

---

## EmbeddyClient API

Async HTTP client wrapping the REST API. All methods return `dict[str, Any]` (parsed JSON).

### Client Constructor

```python
EmbeddyClient(
    base_url: str = "http://localhost:8585",
    *,
    timeout: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | `str` | `"http://localhost:8585"` | Server URL |
| `timeout` | `float` | `30.0` | Request timeout in seconds |
| `transport` | `AsyncBaseTransport \| None` | `None` | Override transport (for testing with ASGITransport) |

Use as an async context manager:

```python
async with EmbeddyClient("http://gpu:8585") as client:
    ...
# or manually:
client = EmbeddyClient("http://gpu:8585")
# ... use client ...
await client.close()
```

Properties: `client.base_url -> str`, `client.timeout -> float`.

### Health and Info

```python
await client.health()     # -> {"status": "ok"}
await client.info()       # -> {"version": "...", "model_name": "...", "dimension": 2048}
```

### Embedding

```python
# Batch embed
result = await client.embed(
    ["text one", "text two"],
    instruction="Represent the document",
)
# -> {"embeddings": [[0.1, ...], [0.2, ...]], "dimension": 2048, "model": "...", "elapsed_ms": 42.5}

# Single query embed
result = await client.embed_query("search query", instruction=None)
# -> {"embedding": [0.1, ...], "dimension": 2048, "model": "...", "elapsed_ms": 12.3}
```

### Client Search

```python
# Full search
result = await client.search(
    "authentication flow",
    collection="code",
    top_k=10,
    mode="hybrid",           # "vector", "fulltext", or "hybrid"
    filters=None,             # Optional dict of SearchFilters fields
    min_score=0.5,
    hybrid_alpha=0.7,
    fusion="rrf",             # "rrf" or "weighted"
)
# -> {"results": [...], "query": "...", "collection": "...", "total_results": 10, "mode": "hybrid", "elapsed_ms": 45.2}

# Find similar
result = await client.find_similar(
    "chunk-uuid-here",
    collection="code",
    top_k=5,
    exclude_self=True,
)
```

Each result item in `results`:

```python
{
    "chunk_id": "uuid",
    "content": "...",
    "score": 0.823,
    "source_path": "src/auth.py",
    "content_type": "python",
    "chunk_type": "function",
    "start_line": 42,
    "end_line": 67,
    "name": "authenticate",
    "metadata": {}
}
```

### Client Ingestion

```python
# Ingest text
result = await client.ingest_text(
    "Some text content",
    collection="docs",
    source="manual-entry",
    content_type="generic",
)
# -> {"files_processed": 1, "chunks_created": 1, "chunks_embedded": 1, "chunks_stored": 1, "chunks_skipped": 0, "errors": [], "elapsed_seconds": 0.5}

# Ingest file (path on the server machine)
result = await client.ingest_file("/data/report.pdf", collection="reports")

# Ingest directory (path on the server machine)
result = await client.ingest_directory(
    "/data/codebase",
    collection="code",
    include=["*.py", "*.md"],
    exclude=["*.pyc"],
    recursive=True,
)

# Reindex a file (delete old + re-ingest)
result = await client.reindex("/data/updated_file.py", collection="code")

# Delete all chunks from a source
result = await client.delete_source("/data/old_file.py", collection="code")
# -> {"deleted_count": 15}
```

### Client Collections

```python
# List all collections
result = await client.list_collections()
# -> {"collections": [{"id": "...", "name": "code", "dimension": 2048, "model_name": "...", "metadata": {}}]}

# Create collection
result = await client.create_collection("my-collection", metadata={"purpose": "testing"})

# Get single collection (raises EmbeddyError if not found)
result = await client.get_collection("my-collection")

# Delete collection
result = await client.delete_collection("my-collection")

# List sources in a collection
result = await client.collection_sources("code")
# -> {"sources": ["src/auth.py", "src/main.py", ...]}

# Get collection statistics
result = await client.collection_stats("code")
# -> {"name": "code", "chunk_count": 1234, "source_count": 56, "dimension": 2048, "model_name": "..."}
```

### Client Chunks

```python
# Get a chunk by ID
result = await client.get_chunk("chunk-uuid", collection="code")
# -> {"chunk_id": "...", "content": "...", "content_type": "python", "source_path": "...", ...}

# Delete a chunk
result = await client.delete_chunk("chunk-uuid", collection="code")
```

---

## REST API Reference

All endpoints are under `/api/v1/`. Content-Type: `application/json`.

### Health and Info Endpoints

**GET /api/v1/health**

```json
// Response 200
{"status": "ok"}
```

**GET /api/v1/info**

```json
// Response 200
{"version": "0.3.12", "model_name": "Qwen/Qwen3-VL-Embedding-2B", "dimension": 2048}
```

### Embedding Endpoints

**POST /api/v1/embed**

Batch embed multiple inputs.

```json
// Request
{
  "inputs": [
    {"text": "hello world"},
    {"text": "foo bar", "image": "/path/to/img.jpg"}
  ],
  "instruction": "Represent the document"  // optional
}

// Response 200
{
  "embeddings": [[0.012, -0.034, ...], [0.056, 0.078, ...]],
  "dimension": 2048,
  "model": "Qwen/Qwen3-VL-Embedding-2B",
  "elapsed_ms": 42.5
}
```

**POST /api/v1/embed/query**

Embed a single query input.

```json
// Request
{
  "input": {"text": "search query"},
  "instruction": null  // optional override
}

// Response 200
{
  "embedding": [0.012, -0.034, ...],
  "dimension": 2048,
  "model": "Qwen/Qwen3-VL-Embedding-2B",
  "elapsed_ms": 12.3
}
```

### Search Endpoints

**POST /api/v1/search**

```json
// Request
{
  "query": "authentication flow",
  "collection": "code",
  "top_k": 10,
  "mode": "hybrid",
  "filters": {
    "content_types": ["python"],
    "source_path_prefix": "src/",
    "chunk_types": ["function"],
    "metadata_match": {"tag": "auth"}
  },
  "min_score": 0.5,
  "hybrid_alpha": 0.7,
  "fusion": "rrf"
}

// Response 200
{
  "results": [
    {
      "chunk_id": "abc-123",
      "content": "def authenticate(username, password): ...",
      "score": 0.8234,
      "source_path": "src/auth.py",
      "content_type": "python",
      "chunk_type": "function",
      "start_line": 42,
      "end_line": 67,
      "name": "authenticate",
      "metadata": {}
    }
  ],
  "query": "authentication flow",
  "collection": "code",
  "total_results": 1,
  "mode": "hybrid",
  "elapsed_ms": 45.2
}
```

**POST /api/v1/search/similar**

```json
// Request
{
  "chunk_id": "abc-123",
  "collection": "code",
  "top_k": 5,
  "exclude_self": true
}

// Response 200 — same shape as search response
```

### Ingestion Endpoints

**POST /api/v1/ingest/text**

```json
// Request
{"text": "content to ingest", "collection": "docs", "source": "manual", "content_type": "generic"}

// Response 200
{
  "files_processed": 1,
  "chunks_created": 1,
  "chunks_embedded": 1,
  "chunks_stored": 1,
  "chunks_skipped": 0,
  "errors": [],
  "elapsed_seconds": 0.5
}
```

**POST /api/v1/ingest/file**

```json
// Request
{"path": "/data/report.pdf", "collection": "reports", "content_type": null}

// Response 200 — same IngestResponse shape
```

**POST /api/v1/ingest/directory**

```json
// Request
{
  "path": "/data/src",
  "collection": "code",
  "include": ["*.py"],
  "exclude": ["*.pyc"],
  "recursive": true
}

// Response 200 — same IngestResponse shape
```

**POST /api/v1/ingest/reindex**

```json
// Request
{"path": "/data/updated.py", "collection": "code"}

// Response 200 — same IngestResponse shape
```

**DELETE /api/v1/ingest/source**

```json
// Request
{"source_path": "/data/old.py", "collection": "code"}

// Response 200
{"deleted_count": 15}
```

### Collection Endpoints

**GET /api/v1/collections**

```json
// Response 200
{
  "collections": [
    {"id": "uuid", "name": "code", "dimension": 2048, "model_name": "Qwen/Qwen3-VL-Embedding-2B", "metadata": {}}
  ]
}
```

**POST /api/v1/collections** (201 on success)

```json
// Request
{"name": "my-collection", "metadata": {"purpose": "testing"}}

// Response 201
{"id": "uuid", "name": "my-collection", "dimension": 2048, "model_name": "...", "metadata": {"purpose": "testing"}}
```

**GET /api/v1/collections/{name}** (404 if not found)

```json
// Response 200
{"id": "uuid", "name": "code", "dimension": 2048, "model_name": "...", "metadata": {}}
```

**DELETE /api/v1/collections/{name}** (404 if not found)

```json
// Response 200
{"message": "Collection 'code' deleted"}
```

**GET /api/v1/collections/{name}/sources** (404 if not found)

```json
// Response 200
{"sources": ["src/auth.py", "src/main.py"]}
```

**GET /api/v1/collections/{name}/stats** (404 if not found)

```json
// Response 200
{"name": "code", "chunk_count": 1234, "source_count": 56, "dimension": 2048, "model_name": "..."}
```

### Chunk Endpoints

**GET /api/v1/chunks/{id}?collection=default** (404 if not found)

```json
// Response 200
{
  "chunk_id": "uuid",
  "content": "def authenticate(...): ...",
  "content_type": "python",
  "chunk_type": "function",
  "source_path": "src/auth.py",
  "start_line": 42,
  "end_line": 67,
  "name": "authenticate",
  "parent": null,
  "metadata": {},
  "content_hash": "sha256:..."
}
```

**DELETE /api/v1/chunks/{id}?collection=default**

```json
// Response 200
{"message": "Chunk deleted"}
```

### Error Responses

All errors return structured JSON:

```json
{
  "error": "ValidationError",
  "message": "Description of what went wrong",
  "details": null
}
```

HTTP status code mapping:
- `ValidationError` -> 400
- All other `EmbeddyError` subclasses -> 500
- Missing resources (collection, chunk) -> 404

---

## Data Types

All types are Pydantic v2 BaseModels. Import from `embeddy` or `embeddy.models`.

### Enums

**ContentType** — Content type of an ingested document:

| Value | Description |
|-------|-------------|
| `PYTHON` | Python source |
| `JAVASCRIPT` | JavaScript source |
| `TYPESCRIPT` | TypeScript source |
| `RUST` | Rust source |
| `GO` | Go source |
| `C` | C source |
| `CPP` | C++ source |
| `JAVA` | Java source |
| `RUBY` | Ruby source |
| `SHELL` | Shell script |
| `MARKDOWN` | Markdown document |
| `RST` | reStructuredText |
| `GENERIC` | Generic text |
| `DOCLING` | Rich document (PDF, DOCX, etc.) |

**SearchMode**: `VECTOR`, `FULLTEXT`, `HYBRID`

**FusionStrategy**: `RRF`, `WEIGHTED`

**DistanceMetric**: `COSINE`, `DOT`

### Embedding Types

**EmbedInput**

```python
class EmbedInput(BaseModel):
    text: str | None = None
    image: str | None = None   # file path, URL, or base64
    video: str | None = None   # file path or URL
    instruction: str | None = None  # per-input instruction override
    # Validator: at least one of text/image/video must be set
```

**Embedding**

```python
class Embedding(BaseModel):
    vector: list[float] | np.ndarray
    model_name: str
    normalized: bool = True
    input_type: str = "text"  # text, image, video, multimodal

    @property
    def dimension(self) -> int: ...
    def to_list(self) -> list[float]: ...  # convert numpy to plain list
```

**SimilarityScore**

```python
class SimilarityScore(BaseModel):
    score: float
    metric: str = "cosine"  # "cosine" or "dot"
    # Supports comparison operators: <, <=, >, >=, ==
```

### Ingestion Types

**SourceMetadata**

```python
class SourceMetadata(BaseModel):
    file_path: str | None = None
    url: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None  # SHA-256
```

**IngestResult** (internal, output of Ingestor)

```python
class IngestResult(BaseModel):
    text: str
    content_type: ContentType
    source: SourceMetadata
    docling_document: Any | None = None
```

### Chunk Types

**Chunk**

```python
class Chunk(BaseModel):
    id: str             # UUID (auto-generated)
    content: str        # Must be non-empty
    content_type: ContentType
    chunk_type: str = "generic"  # function, class, heading_section, paragraph, window, etc.
    source: SourceMetadata
    start_line: int | None = None
    end_line: int | None = None
    name: str | None = None      # function/class name, heading text
    parent: str | None = None    # parent class for methods, parent heading
    metadata: dict[str, Any] = {}
```

### Collection Types

**Collection**

```python
class Collection(BaseModel):
    id: str                # UUID
    name: str              # Must be non-empty
    dimension: int         # Must be >= 1
    model_name: str
    distance_metric: DistanceMetric = DistanceMetric.COSINE
    created_at: datetime
    metadata: dict[str, Any] = {}
```

**CollectionStats**

```python
class CollectionStats(BaseModel):
    name: str
    chunk_count: int = 0
    source_count: int = 0
    dimension: int = 0
    model_name: str = ""
    storage_bytes: int | None = None
```

### Search Types

**SearchFilters**

```python
class SearchFilters(BaseModel):
    content_types: list[ContentType] | None = None
    source_path_prefix: str | None = None
    chunk_types: list[str] | None = None
    metadata_match: dict[str, Any] | None = None
```

**SearchResult**

```python
class SearchResult(BaseModel):
    chunk_id: str
    content: str
    score: float              # Must be finite
    source_path: str | None = None
    content_type: str | None = None
    chunk_type: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    name: str | None = None
    metadata: dict[str, Any] = {}
```

**SearchResults**

```python
class SearchResults(BaseModel):
    results: list[SearchResult] = []  # Sorted by score descending (validated)
    query: str = ""
    collection: str = ""
    mode: SearchMode = SearchMode.HYBRID
    total_results: int = 0
    elapsed_ms: float = 0.0
```

### Pipeline Types

**IngestError** (model, not exception)

```python
class IngestError(BaseModel):
    file_path: str | None = None
    error: str
    error_type: str = ""
```

**IngestStats**

```python
class IngestStats(BaseModel):
    files_processed: int = 0
    chunks_created: int = 0
    chunks_embedded: int = 0
    chunks_stored: int = 0
    chunks_skipped: int = 0  # Skipped due to content-hash dedup
    errors: list[IngestError] = []
    elapsed_seconds: float = 0.0
```

---

## Configuration Reference

All config models are in `embeddy.config`. Import and use programmatically or load from file.

### EmbedderConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `str` | `"local"` | `"local"` (in-process) or `"remote"` (HTTP) |
| `remote_url` | `str \| None` | `None` | Remote embedding server URL. Required when `mode="remote"` |
| `remote_timeout` | `float` | `120.0` | HTTP timeout for remote requests (seconds) |
| `model_name` | `str` | `"Qwen/Qwen3-VL-Embedding-2B"` | HuggingFace model ID or local path |
| `device` | `str \| None` | `None` | Device: `cpu`, `cuda`, `cuda:N`, `mps`, or None (auto). Local mode only |
| `torch_dtype` | `str` | `"bfloat16"` | Model weight dtype: `float32`, `float16`, `bfloat16`. Local mode only |
| `attn_implementation` | `str \| None` | `None` | Attention impl: `flash_attention_2`, `sdpa`, `eager`, or None (auto). Local mode only |
| `trust_remote_code` | `bool` | `True` | Trust remote code when loading model. Local mode only |
| `cache_dir` | `str \| None` | `None` | Model download cache directory. Local mode only |
| `embedding_dimension` | `int` | `2048` | Output dimension (MRL supports 1-2048) |
| `max_length` | `int` | `8192` | Max token sequence length |
| `batch_size` | `int` | `8` | Inputs per encoding batch |
| `normalize` | `bool` | `True` | L2-normalize output vectors |
| `document_instruction` | `str` | `"Represent the user's input."` | Instruction for document encoding |
| `query_instruction` | `str` | `"Retrieve relevant documents, images, or text for the user's query."` | Instruction for query encoding |
| `min_pixels` | `int` | `4096` | Minimum pixel count for images |
| `max_pixels` | `int` | `1843200` | Maximum pixel count for images (1280x1440) |
| `lru_cache_size` | `int` | `1024` | LRU cache entries. 0 to disable |

### StoreConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `db_path` | `str` | `"embeddy.db"` | Path to SQLite database file. Use `":memory:"` for testing |
| `wal_mode` | `bool` | `True` | Enable WAL journal mode for concurrent reads |

### ChunkConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | `str` | `"auto"` | `auto`, `python`, `markdown`, `paragraph`, `token_window`, `docling` |
| `max_tokens` | `int` | `512` | Max tokens per chunk |
| `overlap_tokens` | `int` | `64` | Token overlap for token_window strategy |
| `merge_short` | `bool` | `True` | Merge paragraphs shorter than `min_tokens` |
| `min_tokens` | `int` | `64` | Minimum chunk size before merging |
| `python_granularity` | `str` | `"function"` | `function`, `class`, or `module` |
| `markdown_heading_level` | `int` | `2` | Split markdown at this heading level (1-6) |

Validation: `overlap_tokens` must be less than `max_tokens`.

### PipelineConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `collection` | `str` | `"default"` | Default collection name |
| `concurrency` | `int` | `4` | Max concurrent file processing tasks |
| `include_patterns` | `list[str]` | `[]` | Glob patterns to include in directory ingest |
| `exclude_patterns` | `list[str]` | `[".*", "__pycache__", "node_modules", ".git", "*.pyc", "*.pyo"]` | Glob patterns to exclude |

### ServerConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Bind host |
| `port` | `int` | `8585` | Bind port (1-65535) |
| `workers` | `int` | `1` | Uvicorn worker processes |
| `log_level` | `str` | `"info"` | Logging level: `debug`, `info`, `warning`, `error`, `critical` |
| `cors_origins` | `list[str]` | `["*"]` | CORS allowed origins |

### Config File Format

YAML or JSON. Load with `load_config_file(path)` or set `EMBEDDY_CONFIG_PATH`.

```yaml
embedder:
  mode: remote
  remote_url: http://100.64.0.5:8586
  embedding_dimension: 1024

store:
  db_path: /data/vectors.db

chunk:
  strategy: auto
  max_tokens: 512

pipeline:
  collection: main
  exclude_patterns:
    - ".*"
    - __pycache__

server:
  host: 0.0.0.0
  port: 8585
  workers: 2
```

### Environment Variables

Embedder config fields can be overridden via `EMBEDDY_*` environment variables:

| Variable | Type | Maps To |
|----------|------|---------|
| `EMBEDDY_CONFIG_PATH` | string | Config file path |
| `EMBEDDY_EMBEDDER_MODE` | string | `embedder.mode` |
| `EMBEDDY_REMOTE_URL` | string | `embedder.remote_url` |
| `EMBEDDY_REMOTE_TIMEOUT` | float | `embedder.remote_timeout` |
| `EMBEDDY_MODEL_NAME` | string | `embedder.model_name` |
| `EMBEDDY_DEVICE` | string | `embedder.device` |
| `EMBEDDY_TORCH_DTYPE` | string | `embedder.torch_dtype` |
| `EMBEDDY_EMBEDDING_DIMENSION` | int | `embedder.embedding_dimension` |
| `EMBEDDY_MAX_LENGTH` | int | `embedder.max_length` |
| `EMBEDDY_BATCH_SIZE` | int | `embedder.batch_size` |
| `EMBEDDY_NORMALIZE` | bool | `embedder.normalize` |
| `EMBEDDY_CACHE_DIR` | string | `embedder.cache_dir` |
| `EMBEDDY_TRUST_REMOTE_CODE` | bool | `embedder.trust_remote_code` |
| `EMBEDDY_LRU_CACHE_SIZE` | int | `embedder.lru_cache_size` |

Boolean values: `1/true/yes/on` (true), `0/false/no/off` (false).

Precedence: CLI flags > config file > environment variables > defaults.

---

## Exceptions

All exceptions inherit from `EmbeddyError`. Import from `embeddy` or `embeddy.exceptions`.

| Exception | Description | HTTP Status |
|-----------|-------------|-------------|
| `EmbeddyError` | Base class for all library errors | 500 |
| `ModelLoadError` | Model fails to load (invalid path, insufficient VRAM) | 500 |
| `EncodingError` | Encoding inputs into embeddings fails | 500 |
| `ValidationError` | Domain-level validation (dimension mismatch, invalid config) | 400 |
| `SearchError` | Search operation failure | 500 |
| `IngestError` | Document ingestion failure (file read, content detection) | 500 |
| `StoreError` | Vector store operation failure (DB init, CRUD, indexing) | 500 |
| `ChunkingError` | Document chunking failure (AST parse, heading detection) | 500 |
| `ServerError` | HTTP server lifecycle error | 500 |

Catch the base class for broad handling:

```python
from embeddy.exceptions import EmbeddyError, EncodingError

try:
    result = await embedder.encode("text")
except EncodingError as e:
    print(f"Encoding failed: {e}")
except EmbeddyError as e:
    print(f"Embeddy error: {e}")
```

Note: `embeddy.exceptions.ValidationError` is distinct from `pydantic.ValidationError`.

---

## Content Type Detection

### Text File Extensions

| Extension(s) | ContentType |
|--------------|-------------|
| `.py` | `PYTHON` |
| `.js`, `.mjs`, `.jsx` | `JAVASCRIPT` |
| `.ts`, `.tsx` | `TYPESCRIPT` |
| `.rs` | `RUST` |
| `.go` | `GO` |
| `.c`, `.h` | `C` |
| `.cpp`, `.cc`, `.cxx`, `.hpp` | `CPP` |
| `.java` | `JAVA` |
| `.rb` | `RUBY` |
| `.sh`, `.bash` | `SHELL` |
| `.md`, `.markdown` | `MARKDOWN` |
| `.rst` | `RST` |
| `.txt` | `GENERIC` |

### Docling Document Formats

Files with these extensions are routed through Docling's `DocumentConverter` for structured text extraction:

`.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.tex`, `.latex`

These receive `ContentType.DOCLING` and use the `DoclingChunker`.

---

## Chunking Strategies

When `strategy = "auto"` (default), the chunker is selected by content type:

| Content Type | Chunker | Description |
|-------------|---------|-------------|
| `PYTHON` | `PythonChunker` | AST-based: extracts functions, classes, module-level code with line numbers |
| `MARKDOWN` | `MarkdownChunker` | Splits at configured heading level |
| `DOCLING` | `DoclingChunker` | Bridges Docling's native document chunker |
| All others | `ParagraphChunker` | Paragraph-based with short-paragraph merging |

`TokenWindowChunker` (sliding window with token overlap) is available for explicit use only — it is never auto-selected.

All chunkers implement `BaseChunker.chunk(ingest_result: IngestResult) -> list[Chunk]`.

---

## Hybrid Search Details

Hybrid search runs both vector (KNN) and fulltext (BM25) searches, then fuses results.

**Over-fetching**: Both backends retrieve `top_k * 3` candidates to ensure good coverage after fusion.

### RRF (Reciprocal Rank Fusion) — Default

```
score(d) = sum( 1 / (k + rank_i(d)) )  for each method i
```

Where `k = 60` (standard constant). Rank-based fusion that is robust to score scale differences between vector and BM25 results.

### Weighted Fusion

```
score(d) = alpha * normalized_vector_score + (1 - alpha) * normalized_bm25_score
```

Both score sets are min-max normalized to [0, 1] before combining. `hybrid_alpha` defaults to 0.7 (70% vector, 30% BM25).

---

## Usage Patterns

### RAG Pipeline

Use embeddy as the retrieval backend for a retrieval-augmented generation system:

```python
import asyncio
from embeddy import Embedder, VectorStore, Pipeline, SearchService
from embeddy.config import EmbedderConfig, StoreConfig
from embeddy.models import SearchMode

async def rag_query(question: str) -> str:
    embedder = Embedder(EmbedderConfig(mode="local"))
    store = VectorStore(StoreConfig(db_path="knowledge.db"))
    await store.initialize()
    search = SearchService(embedder=embedder, store=store)

    # Retrieve relevant chunks
    results = await search.search(
        question,
        collection="knowledge",
        top_k=5,
        mode=SearchMode.HYBRID,
    )

    # Build context for LLM
    context = "\n\n---\n\n".join(
        f"[{r.source_path}:{r.start_line}]\n{r.content}"
        for r in results.results
    )

    # Pass context + question to your LLM
    return f"Context:\n{context}\n\nQuestion: {question}"

asyncio.run(rag_query("How does the authentication system work?"))
```

### Code Search

Index a codebase and search for functions, patterns, or concepts:

```python
async def setup_code_search():
    embedder = Embedder(EmbedderConfig(mode="local"))
    store = VectorStore(StoreConfig(db_path="code.db"))
    await store.initialize()

    pipeline = Pipeline(
        embedder=embedder,
        store=store,
        collection="codebase",
        chunk_config=ChunkConfig(
            strategy="auto",              # Uses PythonChunker for .py files
            python_granularity="function", # One chunk per function
        ),
    )

    # Index the entire src directory
    stats = await pipeline.ingest_directory(
        "./src",
        include=["*.py"],
        exclude=["*_test.py", "__pycache__"],
    )
    print(f"Indexed {stats.chunks_stored} code chunks")

    # Search by concept (vector) or by name (fulltext)
    search = SearchService(embedder=embedder, store=store)

    # Find authentication-related code
    results = await search.search("user authentication", "codebase")

    # Find specific function by name
    results = await search.search_fulltext("authenticate_user", "codebase")
```

### Document Search

Index documents (PDFs, DOCX, markdown) for knowledge retrieval:

```python
async def setup_doc_search():
    embedder = Embedder(EmbedderConfig(mode="local"))
    store = VectorStore(StoreConfig(db_path="docs.db"))
    await store.initialize()

    pipeline = Pipeline(embedder=embedder, store=store, collection="docs")

    # Ingest mixed document types
    stats = await pipeline.ingest_directory(
        "./documents",
        include=["*.pdf", "*.docx", "*.md"],
        recursive=True,
    )

    search = SearchService(embedder=embedder, store=store)
    results = await search.search("quarterly revenue projections", "docs")
```

### Incremental Ingestion

Handle file updates efficiently using content-hash deduplication:

```python
async def incremental_update(directory: str):
    # ... setup embedder, store, pipeline ...

    # First run: ingests everything
    stats = await pipeline.ingest_directory(directory, include=["*.py"])
    print(f"Created {stats.chunks_stored}, skipped {stats.chunks_skipped}")

    # Second run (no changes): all files skipped via content hash
    stats = await pipeline.ingest_directory(directory, include=["*.py"])
    print(f"Created {stats.chunks_stored}, skipped {stats.chunks_skipped}")
    # Output: Created 0, skipped N

    # After editing a file: reindex just that file
    stats = await pipeline.reindex_file("./src/changed_module.py")
    print(f"Reindexed: {stats.chunks_stored} chunks")
```
