# Architecture

This document describes the system architecture of embeddy v0.3.11 — the layers, data flow, storage schema, and key design decisions.

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI Layer                           │
│                   (Typer: serve, ingest, search, info)       │
├─────────────────────────────────────────────────────────────┤
│                       Server Layer                          │
│            (FastAPI REST API under /api/v1/)                 │
├─────────────────────────────────────────────────────────────┤
│                       Client Layer                          │
│               (EmbeddyClient: async httpx)                  │
├────────────────────────┬────────────────────────────────────┤
│     Pipeline Layer     │         Search Layer               │
│  (Ingest→Chunk→Embed   │  (Vector + Fulltext + Hybrid)      │
│   →Store)              │  (RRF / Weighted fusion)           │
├────────────────────────┼────────────────────────────────────┤
│   Ingestion Layer      │        Chunking Layer              │
│  (Ingestor, Docling    │  (Python, Markdown, Paragraph,     │
│   routing, hashing)    │   TokenWindow, Docling chunkers)   │
├────────────────────────┴────────────────────────────────────┤
│                     Embedding Layer                         │
│            (Embedder facade + LRU cache)                    │
│       ┌──────────────┬──────────────────┐                   │
│       │ LocalBackend │  RemoteBackend   │                   │
│       │ (in-process) │  (HTTP client)   │                   │
│       └──────────────┴──────────────────┘                   │
├─────────────────────────────────────────────────────────────┤
│                      Storage Layer                          │
│                 (VectorStore: SQLite)                        │
│       ┌──────────────┬──────────────────┐                   │
│       │  sqlite-vec  │      FTS5        │                   │
│       │   (KNN)      │    (BM25)        │                   │
│       └──────────────┴──────────────────┘                   │
├─────────────────────────────────────────────────────────────┤
│                    Configuration Layer                       │
│        (EmbeddyConfig: file + env + CLI overrides)          │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### Ingestion Flow

```
Raw text or file path
       │
       ▼
   Ingestor
       │ detect_content_type()
       │ compute_content_hash()
       │ Route: text file → read directly
       │        rich doc  → Docling DocumentConverter
       ▼
   IngestResult { text, content_type, source, docling_document? }
       │
       ▼
   get_chunker() → BaseChunker subclass
       │ .chunk(ingest_result)
       ▼
   list[Chunk] { id, content, content_type, chunk_type, source, ... }
       │
       ▼
   Embedder.encode([chunk.content for chunk in chunks])
       │ normalize → MRL truncation → L2 normalization
       ▼
   list[Embedding] { vector, model_name, normalized }
       │
       ▼
   VectorStore.add(collection, chunks, embeddings)
       │ INSERT chunks → INSERT vec_chunks → INSERT fts_chunks
       ▼
   IngestStats { files_processed, chunks_created/embedded/stored/skipped }
```

### Search Flow

```
Query string
       │
       ▼
   SearchService.search(query, collection, mode=HYBRID)
       │
       ├──[VECTOR]──→ Embedder.encode_query(query)
       │                    ▼
       │              VectorStore.search_knn()
       │                    ▼
       │              list[SearchResult] (by cosine similarity)
       │
       ├──[FULLTEXT]─→ VectorStore.search_fts()
       │                    ▼
       │              list[SearchResult] (by BM25 score)
       │
       └──[HYBRID]──→ Run BOTH vector + fulltext (over-fetch 3x)
                           ▼
                     Fuse results:
                       RRF: score = Σ 1/(60 + rank_i)
                       Weighted: score = α·vec + (1-α)·bm25
                           ▼
                     Deduplicate, sort, truncate to top_k
                           ▼
                     SearchResults { results, query, mode, elapsed_ms }
```

## Two Deployment Modes

### Library Mode (In-Process)

Everything runs in a single Python process. The consumer imports and composes the components directly:

```python
embedder = Embedder(EmbedderConfig(mode="local"))
store = VectorStore(StoreConfig(db_path="my.db"))
pipeline = Pipeline(embedder=embedder, store=store)
search = SearchService(embedder=embedder, store=store)
```

Suitable when the consumer application runs on a machine with a GPU and wants minimal latency.

### Server Mode (Client-Server)

The **entire server** (embedder, store, pipeline, search) runs on a GPU machine. Client machines use the thin `EmbeddyClient` to make HTTP requests:

```
┌──────────────┐          HTTP           ┌──────────────────────┐
│ Client app   │ ──────────────────────→ │ GPU machine          │
│              │                         │                      │
│ EmbeddyClient│ ← JSON responses ───── │ FastAPI server       │
│              │                         │  ├─ Embedder (GPU)   │
│              │                         │  ├─ VectorStore      │
│              │                         │  ├─ Pipeline         │
│              │                         │  └─ SearchService    │
└──────────────┘                         └──────────────────────┘
```

Key design decision: The client machine does **not** run any model inference. The `EmbeddyClient` is a thin HTTP wrapper — it sends text/paths to the server and receives results. This keeps client dependencies minimal (only `httpx`).

### Embedder Backend Modes

Within either deployment mode, the `Embedder` delegates to a backend:

- **LocalBackend**: Loads the Qwen3-VL model in-process. Uses `asyncio.to_thread()` for all synchronous operations (model loading, inference). Requires GPU + torch.

- **RemoteBackend**: Calls a dedicated embedding server via HTTP (`httpx.AsyncClient`). The remote server exposes `POST /encode` and `GET /health`. Useful for offloading GPU inference to a separate process or machine.

The backend is selected automatically based on `EmbedderConfig.mode`:
- `mode="local"` → `LocalBackend`
- `mode="remote"` → `RemoteBackend` (requires `remote_url`)

## Storage Architecture

### SQLite + Extensions

embeddy uses a single SQLite database with two extensions:

1. **sqlite-vec** — Vector similarity search via virtual tables. Each collection gets its own `vec_chunks_{id}` table with `float[N]` embedding columns.

2. **FTS5** — Full-text search with BM25 ranking. Each collection gets its own `fts_chunks_{id}` table indexing `content` and `name` columns using Porter stemming + Unicode61 tokenizer.

### Database Schema

```sql
-- Namespace table
CREATE TABLE collections (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    dimension INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    distance_metric TEXT NOT NULL DEFAULT 'cosine',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT
);

-- Chunk metadata
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id),
    content TEXT NOT NULL,
    content_type TEXT NOT NULL,
    chunk_type TEXT,
    source_path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    name TEXT,
    parent TEXT,
    metadata TEXT,
    content_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_chunks_collection ON chunks(collection_id);
CREATE INDEX idx_chunks_source ON chunks(collection_id, source_path);
CREATE INDEX idx_chunks_content_hash ON chunks(content_hash);
CREATE INDEX idx_chunks_content_type ON chunks(collection_id, content_type);

-- Per-collection virtual tables (created when collection is created)
CREATE VIRTUAL TABLE vec_chunks_{safe_id} USING vec0(
    id TEXT PRIMARY KEY,
    embedding float[{dimension}]
);

CREATE VIRTUAL TABLE fts_chunks_{safe_id} USING fts5(
    content, name, chunk_id UNINDEXED,
    tokenize='porter unicode61'
);
```

### WAL Mode

WAL (Write-Ahead Logging) is enabled by default for file-based databases. This allows concurrent reads while writes are serialized by SQLite's internal locking. Sufficient for single-process use.

### Async Pattern

All SQLite operations are synchronous (sqlite3 module limitation). The `VectorStore` wraps them in `asyncio.to_thread()` so they run in the default thread pool without blocking the event loop. The connection is created with `check_same_thread=False` since different threads in the pool may execute operations.

## Chunking Strategy

### Auto-Selection

When `ChunkConfig.strategy = "auto"` (the default), the chunker is selected based on content type:

| Content Type | Chunker | Description |
|-------------|---------|-------------|
| `PYTHON` | `PythonChunker` | AST-based: extracts functions, classes, module-level code |
| `MARKDOWN` | `MarkdownChunker` | Splits at configured heading level |
| `DOCLING` | `DoclingChunker` | Bridges Docling's native chunker |
| All others | `ParagraphChunker` | Paragraph-based with short-paragraph merging |

`TokenWindowChunker` is available for explicit use (sliding window with overlap) but is not auto-selected.

### Chunker Interface

All chunkers extend `BaseChunker` and implement:

```python
class BaseChunker(ABC):
    def __init__(self, config: ChunkConfig) -> None: ...

    @abstractmethod
    def chunk(self, ingest_result: IngestResult) -> list[Chunk]: ...
```

## Content-Hash Deduplication

The pipeline uses SHA-256 content hashing for deduplication:

1. When a file is ingested, its full text is hashed via `compute_content_hash()`
2. The hash is stored in the `content_hash` column of the `chunks` table
3. On subsequent `ingest_file()` calls, the pipeline checks `VectorStore.has_content_hash()` before processing
4. If the hash already exists, the file is skipped (`chunks_skipped` is incremented)
5. `reindex_file()` bypasses dedup by deleting existing chunks first

## MRL Dimension Truncation

Qwen3-VL-Embedding-2B supports Matryoshka Representation Learning (MRL), meaning embeddings can be truncated to smaller dimensions without retraining:

1. The model produces full 2048-dimensional vectors
2. If `EmbedderConfig.embedding_dimension < 2048`, the `Embedder` truncates to the first N dimensions
3. After truncation, L2 normalization is re-applied (if `normalize=True`)
4. Valid dimension range: 1-2048

This allows trading recall quality for storage efficiency and search speed.

## Server Architecture

### Factory Pattern

`create_app()` is a FastAPI application factory that accepts pre-built dependencies:

```python
app = create_app(
    embedder=embedder,
    store=store,
    pipeline=pipeline,
    search_service=search_service,
)
```

Dependencies are stored on `app.state` and accessed by route handlers. This makes the server trivially testable — tests inject mocks, production injects real objects.

### Route Organization

Routes are organized into separate modules under `server/routes/`:
- `health.py` — GET /health, GET /info
- `embed.py` — POST /embed, POST /embed/query
- `search.py` — POST /search, POST /search/similar
- `ingest.py` — POST /ingest/text, POST /ingest/file, POST /ingest/directory, POST /ingest/reindex, DELETE /ingest/source
- `collections.py` — Collection CRUD
- `chunks.py` — Chunk CRUD

All routes are mounted under `/api/v1/`.

### Error Handling

`EmbeddyError` subclasses are mapped to HTTP status codes via a global exception handler:
- `ValidationError` → 400
- All other `EmbeddyError` subclasses → 500

Errors return structured JSON: `{"error": "error_type", "message": "description"}`.

## Design Decisions

1. **SQLite over Postgres/Qdrant/Pinecone**: Zero-config, single-file database. sqlite-vec provides good enough KNN performance for single-machine workloads. FTS5 provides BM25 without an external search engine.

2. **Async-native with `to_thread()`**: The public API is fully async, but SQLite and model inference are synchronous. Using `asyncio.to_thread()` bridges this gap without requiring separate async database drivers.

3. **Per-collection virtual tables**: Each collection gets its own vec and FTS tables. This provides namespace isolation and allows independent indexing/deletion without cross-collection interference.

4. **Hybrid search by default**: RRF fusion of vector + BM25 results provides better recall than either method alone, with minimal latency overhead (both searches can run against the same SQLite database).

5. **Content-hash dedup**: Avoids re-processing unchanged files during incremental directory ingestion. The SHA-256 hash is computed on the full text content, not file metadata.

6. **Server on GPU machine**: In client-server mode, the entire application (including VectorStore) runs on the GPU machine. The client is a thin HTTP wrapper. This simplifies deployment — no database sync between machines.

7. **Instruction-aware embeddings**: Qwen3-VL uses different instructions for queries vs documents. `encode_query()` and `encode_document()` apply the appropriate instruction automatically.

8. **LRU cache in Embedder**: Single-input encodings are cached by `(input, instruction)` hash. Batch encodings bypass the cache. This optimizes repeated query patterns without excessive memory use.
