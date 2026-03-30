# Wikipedia Example

Large-scale ingest, search, and benchmark demonstration for **embeddy**.

This example downloads Simple English Wikipedia articles, ingests them through the embeddy pipeline (chunk, embed, store), and provides interactive search and performance benchmarking.

## Prerequisites

```bash
# Install embeddy with all extras
pip install -e ".[all]"

# Optional: install HuggingFace datasets for full Wikipedia download
pip install datasets
```

Without `datasets`, the scripts fall back to a small built-in sample of 5 articles.

## Quick Start

### 1. Download articles

```bash
python examples/wikipedia/download.py --output-dir ./data --max-articles 1000
```

Options:
- `--output-dir` — where to save `articles.jsonl` (default: `./data`)
- `--max-articles` — maximum articles to keep (default: 1000)
- `--min-length` — minimum text length to filter short stubs (default: 100)

### 2. Ingest into embeddy

```bash
python examples/wikipedia/ingest.py \
  --data-file ./data/articles.jsonl \
  --db ./data/embeddy.db \
  --collection wikipedia
```

Options:
- `--data-file` — path to the JSONL file from step 1
- `--db` — SQLite database path
- `--collection` — target collection name (default: `wikipedia`)
- `--model` — embedding model name (default: `Qwen/Qwen3-Embedding-0.6B`)

### 3. Search

Single query:

```bash
python examples/wikipedia/search.py \
  --query "what is machine learning" \
  --top-k 5 \
  --db ./data/embeddy.db
```

Interactive mode:

```bash
python examples/wikipedia/search.py --interactive --db ./data/embeddy.db
```

Options:
- `--query` / `-q` — search query
- `--top-k` / `-k` — number of results (default: 5)
- `--mode` / `-m` — search mode: `vector`, `fulltext`, or `hybrid` (default: `hybrid`)
- `--json` — output as JSON
- `--interactive` / `-i` — interactive search loop

### 4. Benchmark

```bash
python examples/wikipedia/benchmark.py \
  --data-file ./data/articles.jsonl \
  --db ./data/bench.db \
  --num-articles 100 \
  --num-queries 20
```

Measures:
- **Ingest throughput**: articles/sec, chunks/sec
- **Search latency**: avg, p50, p95, p99 per mode (vector, fulltext, hybrid)
- **Queries/sec** across all modes

Options:
- `--num-articles` — articles to ingest for benchmark (default: 100)
- `--num-queries` — queries to run per mode (default: 20)
- `--json` — output as JSON for programmatic consumption

## File Format

Articles are stored in [JSONL](https://jsonlines.org/) format — one JSON object per line:

```json
{"title": "Python (programming language)", "text": "Python is a high-level...", "article_id": "1"}
{"title": "Mathematics", "text": "Mathematics is an area...", "article_id": "2"}
```

## Architecture

```
download.py   →  articles.jsonl  →  ingest.py   →  embeddy.db
                                                        ↓
                                     search.py   ←  SearchService
                                     benchmark.py ←  Pipeline + SearchService
```

- **download.py** — Fetches articles, filters by length, saves as JSONL
- **ingest.py** — Reads JSONL, ingests each article through `Pipeline.ingest_text()`
- **search.py** — Queries the collection via `SearchService.search()`
- **benchmark.py** — Measures throughput and latency with configurable parameters
