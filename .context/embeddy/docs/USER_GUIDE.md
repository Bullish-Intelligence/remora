# User Guide

This guide covers day-to-day usage of embeddy: CLI commands, configuration, deployment modes, content handling, and search strategies.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
  - [embeddy --version](#embeddy---version)
  - [embeddy info](#embeddy-info)
  - [embeddy serve](#embeddy-serve)
  - [embeddy ingest text](#embeddy-ingest-text)
  - [embeddy ingest file](#embeddy-ingest-file)
  - [embeddy ingest dir](#embeddy-ingest-dir)
  - [embeddy search](#embeddy-search)
- [Configuration](#configuration)
  - [Config File Format](#config-file-format)
  - [Environment Variables](#environment-variables)
  - [CLI Overrides](#cli-overrides)
  - [Precedence](#precedence)
- [Deployment Modes](#deployment-modes)
  - [Library Mode](#library-mode)
  - [Server Mode](#server-mode)
- [Content Types and Chunking](#content-types-and-chunking)
  - [Automatic Detection](#automatic-detection)
  - [Text File Extensions](#text-file-extensions)
  - [Docling Document Formats](#docling-document-formats)
  - [Chunking Strategies](#chunking-strategies)
- [Search Modes](#search-modes)
  - [Vector Search](#vector-search)
  - [Full-Text Search](#full-text-search)
  - [Hybrid Search](#hybrid-search)
  - [Choosing a Search Mode](#choosing-a-search-mode)
- [Content Deduplication](#content-deduplication)
- [Database Management](#database-management)

---

## Installation

embeddy is distributed as a Python package with optional extras:

```bash
# Core library (embedding, chunking, storage, search)
pip install embeddy

# With HTTP server support
pip install embeddy[server]

# With CLI support
pip install embeddy[cli]

# Everything (server + CLI + benchmarks + dev tools)
pip install embeddy[all]
```

Requires Python 3.13+.

## Quick Start

```bash
# Check version
embeddy --version

# Ingest a file
embeddy ingest file ./my_document.md

# Ingest a directory of Python files
embeddy ingest dir ./src --include "*.py"

# Search
embeddy search "how does authentication work"

# Start the HTTP server
embeddy serve
```

## CLI Reference

All CLI commands support `--help` for detailed option information.

### embeddy --version

Print the version and exit.

```bash
$ embeddy --version
embeddy 0.3.11
```

### embeddy info

Show version, default configuration values, and system info.

```bash
$ embeddy info
embeddy 0.3.11

Default configuration:
  embedder.model_name      : Qwen/Qwen3-VL-Embedding-2B
  embedder.mode            : local
  embedder.dimension       : 2048
  embedder.normalize       : True
  store.db_path            : embeddy.db
  pipeline.collection      : default
  server.host              : 127.0.0.1
  server.port              : 8585
```

### embeddy serve

Start the embeddy HTTP server.

```bash
embeddy serve [OPTIONS]
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--config` | `-c` | Path to config file (YAML/JSON) | None |
| `--host` | `-h` | Host to bind to | From config (127.0.0.1) |
| `--port` | `-p` | Port to bind to | From config (8585) |
| `--db` | | SQLite database path | From config (embeddy.db) |
| `--log-level` | `-l` | Log level (debug/info/warning/error) | From config (info) |

Example:

```bash
# Start with defaults
embeddy serve

# Start on all interfaces, custom port, with config file
embeddy serve -c config.yaml --host 0.0.0.0 --port 9000
```

The server loads the embedding model on startup and exposes all API endpoints under `/api/v1/`. Requires the `server` extra (`pip install embeddy[server]`).

### embeddy ingest text

Ingest raw text into a collection.

```bash
embeddy ingest text TEXT [OPTIONS]
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--collection` | `-C` | Target collection | `default` |
| `--source` | `-s` | Source identifier | None |
| `--config` | `-c` | Config file path | None |
| `--db` | | SQLite database path | From config |
| `--json` | | Output as JSON | False |

Example:

```bash
embeddy ingest text "Embeddy is an async-native embedding library" -C docs
embeddy ingest text "Some content" --source "manual-entry" --json
```

### embeddy ingest file

Ingest a single file into a collection. Content type is detected from the file extension.

```bash
embeddy ingest file PATH [OPTIONS]
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--collection` | `-C` | Target collection | `default` |
| `--config` | `-c` | Config file path | None |
| `--db` | | SQLite database path | From config |
| `--json` | | Output as JSON | False |

Example:

```bash
embeddy ingest file ./README.md
embeddy ingest file ./src/main.py -C code --json
```

Output shows ingestion statistics:

```
Ingest complete:
  files processed : 1
  chunks created  : 12
  chunks embedded : 12
  chunks stored   : 12
  chunks skipped  : 0
  elapsed         : 1.234s
```

### embeddy ingest dir

Ingest all files in a directory into a collection.

```bash
embeddy ingest dir PATH [OPTIONS]
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--collection` | `-C` | Target collection | `default` |
| `--include` | `-i` | Include glob pattern (e.g. `*.py`) | None (all files) |
| `--exclude` | `-e` | Exclude glob pattern (e.g. `*.pyc`) | None |
| `--recursive/--no-recursive` | | Recurse into subdirectories | `--recursive` |
| `--config` | `-c` | Config file path | None |
| `--db` | | SQLite database path | From config |
| `--json` | | Output as JSON | False |

Example:

```bash
# Ingest all Python files recursively
embeddy ingest dir ./src --include "*.py" -C codebase

# Ingest a flat directory of markdown files
embeddy ingest dir ./docs --include "*.md" --no-recursive

# Ingest everything, excluding build artifacts
embeddy ingest dir ./project --exclude "*.pyc"
```

Default exclude patterns (from `PipelineConfig`): `.*`, `__pycache__`, `node_modules`, `.git`, `*.pyc`, `*.pyo`.

### embeddy search

Search a collection.

```bash
embeddy search QUERY [OPTIONS]
```

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--collection` | `-C` | Collection to search | `default` |
| `--top-k` | `-k` | Number of results | 10 |
| `--mode` | `-m` | Search mode: `vector`, `fulltext`, `hybrid` | `hybrid` |
| `--min-score` | | Minimum score threshold | None |
| `--config` | `-c` | Config file path | None |
| `--db` | | SQLite database path | From config |
| `--json` | | Output as JSON | False |

Example:

```bash
# Default hybrid search
embeddy search "authentication flow"

# Vector-only search, top 5
embeddy search "how to deploy" -m vector -k 5

# Full-text search with JSON output
embeddy search "error handling" -m fulltext --json

# Search with minimum score threshold
embeddy search "database schema" --min-score 0.5
```

Output:

```
Search: 3 result(s) for 'authentication flow' (mode=hybrid, 45.32ms)

  [1] score=0.8234  source=src/auth.py
      def authenticate(username, password):
          """Authenticate a user against the database..."""...

  [2] score=0.7891  source=docs/auth.md
      # Authentication Flow
      Users authenticate via OAuth2...

  [3] score=0.6543  source=src/middleware.py
      class AuthMiddleware:
          """Validates JWT tokens on incoming requests..."""...
```

## Configuration

embeddy uses a layered configuration system. Values are resolved in this order: defaults, config file, environment variables, CLI flags.

### Config File Format

Configuration files use YAML or JSON. All sections are optional — missing sections use defaults.

**YAML example** (`embeddy.yaml`):

```yaml
embedder:
  mode: local
  model_name: Qwen/Qwen3-VL-Embedding-2B
  embedding_dimension: 2048
  normalize: true
  batch_size: 8
  max_length: 8192
  lru_cache_size: 1024
  device: cuda
  torch_dtype: bfloat16

store:
  db_path: ./data/embeddy.db
  wal_mode: true

chunk:
  strategy: auto
  max_tokens: 512
  overlap_tokens: 64
  merge_short: true
  min_tokens: 64
  python_granularity: function
  markdown_heading_level: 2

pipeline:
  collection: default
  concurrency: 4
  include_patterns: []
  exclude_patterns:
    - ".*"
    - __pycache__
    - node_modules
    - .git
    - "*.pyc"
    - "*.pyo"

server:
  host: 127.0.0.1
  port: 8585
  workers: 1
  log_level: info
  cors_origins:
    - "*"
```

**JSON example** (`embeddy.json`):

```json
{
  "embedder": {
    "mode": "local",
    "embedding_dimension": 1024
  },
  "store": {
    "db_path": "./my_vectors.db"
  },
  "server": {
    "port": 9000
  }
}
```

Load a config file explicitly or via environment variable:

```bash
# Explicit path
embeddy serve -c /path/to/embeddy.yaml

# Environment variable
export EMBEDDY_CONFIG_PATH=/path/to/embeddy.yaml
embeddy serve
```

### Environment Variables

All embedder settings can be overridden via `EMBEDDY_*` environment variables:

| Variable | Type | Maps To |
|----------|------|---------|
| `EMBEDDY_CONFIG_PATH` | string | Config file path (used by `load_config_file()`) |
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

Boolean values accept: `1`, `true`, `yes`, `on` (true) or `0`, `false`, `no`, `off` (false).

### CLI Overrides

CLI flags override both config file and environment variable values for the options they cover:

- `--db` overrides `store.db_path`
- `--host` overrides `server.host`
- `--port` overrides `server.port`
- `--log-level` overrides `server.log_level`
- `--collection` / `-C` overrides `pipeline.collection`

### Precedence

Values are resolved in this order (highest priority first):

1. CLI flags
2. Config file (loaded via `-c` flag or `EMBEDDY_CONFIG_PATH`)
3. `EMBEDDY_*` environment variables (embedder config only)
4. Built-in defaults

## Deployment Modes

### Library Mode

Import embeddy components directly into your Python application. Everything runs in a single process. Best for applications running on a GPU machine.

```python
import asyncio
from embeddy import Embedder, VectorStore, Pipeline, SearchService
from embeddy.config import EmbedderConfig, StoreConfig

async def main():
    embedder = Embedder(EmbedderConfig(mode="local"))
    store = VectorStore(StoreConfig(db_path="my_vectors.db"))
    await store.initialize()

    pipeline = Pipeline(embedder=embedder, store=store, collection="docs")
    search = SearchService(embedder=embedder, store=store)

    # Ingest
    stats = await pipeline.ingest_directory("./documents", include=["*.md"])
    print(f"Ingested {stats.chunks_stored} chunks")

    # Search
    results = await search.search("how does X work", collection="docs")
    for r in results.results:
        print(f"  {r.score:.4f}  {r.source_path}")

asyncio.run(main())
```

### Server Mode

Run the full application on a GPU machine, connect from client machines via HTTP.

**GPU machine:**

```bash
embeddy serve --host 0.0.0.0 --port 8585
```

**Client machine:**

```python
import asyncio
from embeddy import EmbeddyClient

async def main():
    async with EmbeddyClient("http://gpu-machine:8585") as client:
        # Ingest
        result = await client.ingest_file("/data/report.pdf", collection="reports")

        # Search
        results = await client.search("quarterly revenue", collection="reports")
        for r in results["results"]:
            print(f"  {r['score']:.4f}  {r['source_path']}")

asyncio.run(main())
```

The client machine only needs `httpx` — no GPU, no torch, no model weights.

## Content Types and Chunking

### Automatic Detection

embeddy detects content type from file extensions and routes files to the appropriate chunker automatically.

### Text File Extensions

| Extension(s) | Content Type | Chunker |
|--------------|-------------|---------|
| `.py` | PYTHON | PythonChunker (AST-based) |
| `.js`, `.mjs`, `.jsx` | JAVASCRIPT | ParagraphChunker |
| `.ts`, `.tsx` | TYPESCRIPT | ParagraphChunker |
| `.rs` | RUST | ParagraphChunker |
| `.go` | GO | ParagraphChunker |
| `.c`, `.h` | C | ParagraphChunker |
| `.cpp`, `.cc`, `.cxx`, `.hpp` | CPP | ParagraphChunker |
| `.java` | JAVA | ParagraphChunker |
| `.rb` | RUBY | ParagraphChunker |
| `.sh`, `.bash` | SHELL | ParagraphChunker |
| `.md`, `.markdown` | MARKDOWN | MarkdownChunker |
| `.rst` | RST | ParagraphChunker |
| `.txt` | GENERIC | ParagraphChunker |

### Docling Document Formats

Rich document formats are routed through [Docling](https://github.com/DS4SD/docling) for conversion before chunking:

`.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif`, `.bmp`, `.tex`, `.latex`

These files are converted to structured text by Docling's `DocumentConverter`, then chunked using the `DoclingChunker`.

### Chunking Strategies

| Strategy | Selection | Description |
|----------|-----------|-------------|
| `auto` | Default | Selects chunker based on content type (see table above) |
| `python` | Explicit | AST-based: extracts functions, classes, module-level code with line numbers |
| `markdown` | Explicit | Splits at heading level (configurable, default level 2) |
| `paragraph` | Explicit | Paragraph-based with short-paragraph merging |
| `token_window` | Explicit only | Sliding window with token overlap (not auto-selected) |
| `docling` | Auto for Docling types | Bridges Docling's native document chunker |

Configure chunking in the config file:

```yaml
chunk:
  strategy: auto         # or: python, markdown, paragraph, token_window, docling
  max_tokens: 512        # Maximum tokens per chunk
  overlap_tokens: 64     # Overlap for token_window strategy
  merge_short: true      # Merge paragraphs shorter than min_tokens
  min_tokens: 64         # Minimum chunk size before merging
  python_granularity: function  # function, class, or module
  markdown_heading_level: 2     # Split markdown at this heading level (1-6)
```

## Search Modes

### Vector Search

Semantic similarity search using cosine distance on embedding vectors. Best for natural language queries where meaning matters more than exact wording.

```bash
embeddy search "how to handle errors gracefully" -m vector
```

The query is embedded using the same model (with query-specific instruction), then compared against stored vectors via sqlite-vec KNN.

### Full-Text Search

BM25 keyword matching via FTS5. Best for queries containing specific identifiers, error codes, or exact phrases.

```bash
embeddy search "ValueError: invalid dimension" -m fulltext
```

Uses Porter stemming and Unicode61 tokenization. Matches against chunk content and name fields.

### Hybrid Search

Combines vector and full-text results using score fusion. This is the default mode and typically produces the best results.

```bash
embeddy search "database connection timeout" -m hybrid
```

Fusion strategies:
- **RRF (Reciprocal Rank Fusion)**: `score(d) = sum(1 / (60 + rank_i))`. Default strategy. Rank-based, robust to score scale differences.
- **Weighted**: `score = alpha * vector_score + (1 - alpha) * bm25_score` after min-max normalization. Configurable via `hybrid_alpha` (default 0.7 = 70% vector weight).

Hybrid search over-fetches `top_k * 3` from both backends before fusing to ensure good coverage.

### Choosing a Search Mode

| Use Case | Recommended Mode |
|----------|-----------------|
| General-purpose queries | `hybrid` (default) |
| Conceptual / semantic questions | `vector` |
| Exact identifier or error lookup | `fulltext` |
| Code search by function name | `fulltext` |
| "Find similar to this concept" | `vector` |

## Content Deduplication

embeddy uses SHA-256 content hashing for deduplication during ingestion:

1. When a file is ingested, its full text is hashed
2. If a chunk with the same hash already exists in the collection, the file is skipped
3. `chunks_skipped` in the ingest stats indicates how many files were deduplicated
4. To force re-ingestion of a changed file, use `reindex_file()` (Pipeline API) or `POST /ingest/reindex` (server API), which deletes existing chunks before re-ingesting

## Database Management

The database is a single SQLite file (default: `embeddy.db` in the working directory).

- **Location**: Set via `store.db_path` in config, `--db` CLI flag, or programmatically
- **WAL mode**: Enabled by default for concurrent read performance
- **Backup**: Copy the `.db` file while the application is stopped, or use SQLite's `.backup` command
- **Size**: Depends on number of chunks and embedding dimension. A collection with 100k chunks at 2048 dimensions uses approximately 800MB

To use an in-memory database for testing, set `db_path` to `":memory:"`.
