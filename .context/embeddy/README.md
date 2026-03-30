# embeddy

Async-native multimodal embedding, chunking, hybrid search, and RAG pipeline library for Python.

**v0.3.11** | Python 3.13+ | MIT License

## What It Does

embeddy is an end-to-end pipeline for turning documents into searchable embeddings. It handles ingestion, chunking, embedding, storage, and hybrid search (vector + full-text) in a single async-native library.

- **Multimodal embeddings** via Qwen3-VL-Embedding-2B (text, image, video)
- **Smart chunking** — AST-based Python chunker, Markdown heading chunker, paragraph merger, token-window slider, Docling bridge for PDFs/DOCX
- **Hybrid search** — vector (KNN via sqlite-vec) + full-text (BM25 via FTS5) with RRF or weighted fusion
- **Two deployment modes** — use as an in-process library, or run as a client-server system
- **Content-hash deduplication** — skip re-ingesting unchanged files
- **MRL dimension truncation** — reduce embedding dimensions (64-2048) without retraining

## Architecture at a Glance

```
Document -> Ingestor -> Chunker -> Embedder -> VectorStore -> SearchService
                                      |
                              LocalBackend (GPU)
                                  or
                              RemoteBackend (HTTP)
```

**Library mode**: Import `Pipeline` and `SearchService` directly. Everything runs in-process.

**Server mode**: Run `embeddy serve` on a GPU machine. Connect from client machines via `EmbeddyClient`.

## Quick Start

### Installation

```bash
# Core library
pip install embeddy

# With server support (FastAPI + uvicorn)
pip install embeddy[server]

# With CLI support (typer)
pip install embeddy[cli]

# Everything
pip install embeddy[all]
```

### Library Usage

```python
import asyncio
from embeddy import (
    EmbedderConfig, StoreConfig, ChunkConfig,
    Embedder, VectorStore, Pipeline, SearchService,
)

async def main():
    # Configure
    embedder = Embedder(EmbedderConfig())
    store = VectorStore(StoreConfig(db_path="my_project.db"))
    await store.initialize()
    await embedder._backend.load()

    # Build pipeline and search service
    pipeline = Pipeline(embedder=embedder, store=store, collection="docs")
    search = SearchService(embedder=embedder, store=store)

    # Ingest a directory
    stats = await pipeline.ingest_directory("./src", include=["*.py", "*.md"])
    print(f"Ingested {stats.chunks_stored} chunks from {stats.files_processed} files")

    # Search
    results = await search.search("how does authentication work?", collection="docs")
    for hit in results.results:
        print(f"  [{hit.score:.4f}] {hit.source_path}:{hit.start_line}")
        print(f"    {hit.content[:120]}")

asyncio.run(main())
```

### CLI Usage

```bash
# Start the server
embeddy serve --host 0.0.0.0 --port 8585 --db my_project.db

# Ingest files
embeddy ingest file ./README.md --collection docs
embeddy ingest dir ./src --include "*.py" --collection code

# Search
embeddy search "authentication flow" --collection code --mode hybrid --top-k 5

# Show info
embeddy info
embeddy --version
```

### Client Usage (Remote)

```python
from embeddy import EmbeddyClient

async with EmbeddyClient("http://gpu-machine:8585") as client:
    # Ingest
    await client.ingest_directory("./src", collection="code", include=["*.py"])

    # Search
    result = await client.search("error handling", collection="code", top_k=5)
    for hit in result["results"]:
        print(f"  [{hit['score']:.4f}] {hit['source_path']}")
```

## Configuration

embeddy uses a layered config system: defaults -> config file -> environment variables -> CLI flags.

### Config File (YAML)

```yaml
embedder:
  mode: local                          # or "remote"
  model_name: Qwen/Qwen3-VL-Embedding-2B
  embedding_dimension: 2048
  batch_size: 8
  normalize: true
  lru_cache_size: 1024

store:
  db_path: embeddy.db
  wal_mode: true

chunk:
  strategy: auto                       # auto, python, markdown, paragraph, token_window, docling
  max_tokens: 512
  overlap_tokens: 64

pipeline:
  collection: default
  concurrency: 4
  exclude_patterns: [".*", "__pycache__", "node_modules", ".git", "*.pyc"]

server:
  host: 127.0.0.1
  port: 8585
  workers: 1
  log_level: info
```

```bash
# Load from file
export EMBEDDY_CONFIG_PATH=./embeddy.yaml

# Or override individual settings
export EMBEDDY_EMBEDDER_MODE=remote
export EMBEDDY_REMOTE_URL=http://gpu-machine:8586
export EMBEDDY_EMBEDDING_DIMENSION=512
```

## Key Components

| Layer | Class | Purpose |
|-------|-------|---------|
| Embedding | `Embedder` | Facade with LRU cache, MRL truncation, L2 normalization |
| Embedding | `LocalBackend` / `RemoteBackend` | In-process or HTTP-based model inference |
| Chunking | `PythonChunker` | AST-based: splits by function/class/module |
| Chunking | `MarkdownChunker` | Splits by heading level |
| Chunking | `ParagraphChunker` | Paragraph-based with short-paragraph merging |
| Chunking | `TokenWindowChunker` | Fixed-size sliding window with overlap |
| Chunking | `DoclingChunker` | Bridge for Docling's document chunking |
| Storage | `VectorStore` | sqlite-vec (KNN) + FTS5 (BM25), WAL mode, per-collection virtual tables |
| Ingestion | `Ingestor` | Text/file ingestion, content type detection, Docling routing |
| Pipeline | `Pipeline` | Composes Ingestor -> Chunker -> Embedder -> VectorStore |
| Search | `SearchService` | Vector, full-text, and hybrid search with RRF/weighted fusion |
| Server | `create_app()` | FastAPI REST API factory |
| Client | `EmbeddyClient` | Async httpx client mirroring all server endpoints |
| CLI | `embeddy` | Typer CLI: serve, ingest, search, info |

## REST API

All endpoints under `/api/v1/`. See [SPEC.md](SPEC.md) for full details.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Health check |
| GET | `/info` | Version, model, dimension |
| POST | `/embed` | Batch embed inputs |
| POST | `/embed/query` | Embed a single query |
| POST | `/search` | Search (vector/fulltext/hybrid) |
| POST | `/search/similar` | Find similar chunks |
| POST | `/ingest/text` | Ingest raw text |
| POST | `/ingest/file` | Ingest file by path |
| POST | `/ingest/directory` | Ingest directory |
| POST | `/ingest/reindex` | Re-ingest a file |
| DELETE | `/ingest/source` | Delete chunks by source |
| GET/POST/DELETE | `/collections` | Collection CRUD |
| GET/DELETE | `/chunks/{id}` | Chunk CRUD |

## Documentation

| Document | Description |
|----------|-------------|
| [SPEC.md](SPEC.md) | Technical specification — data structures, API contracts, config reference |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture — layer diagram, data flow, design decisions |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | End-user guide — CLI, configuration, deployment |
| [docs/DEV_GUIDE.md](docs/DEV_GUIDE.md) | Developer guide — testing, code style, project structure |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Integration guide — the one-stop reference for using embeddy in your projects |

## Project Info

- **Author**: Bullish Design
- **License**: MIT
- **Python**: 3.13+
- **Build**: hatchling
- **Package Manager**: uv
- **Target Model**: Qwen/Qwen3-VL-Embedding-2B
