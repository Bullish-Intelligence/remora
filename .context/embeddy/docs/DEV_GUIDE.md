# Developer Guide

This guide covers project structure, development setup, testing, code style, and how to extend embeddy with new components.

## Table of Contents

- [Project Structure](#project-structure)
- [Development Setup](#development-setup)
  - [Prerequisites](#prerequisites)
  - [Nix + devenv (Recommended)](#nix--devenv-recommended)
  - [Manual Setup](#manual-setup)
- [Running Tests](#running-tests)
  - [Test Configuration](#test-configuration)
  - [Running Specific Tests](#running-specific-tests)
  - [Coverage](#coverage)
- [Code Style](#code-style)
  - [Ruff](#ruff)
  - [Mypy](#mypy)
  - [General Conventions](#general-conventions)
- [How to Add a New Chunker](#how-to-add-a-new-chunker)
- [How to Add a New Route](#how-to-add-a-new-route)
- [How to Add a New Config Field](#how-to-add-a-new-config-field)
- [Versioning](#versioning)
- [Git Workflow](#git-workflow)

---

## Project Structure

```
embeddy/
├── src/embeddy/                  # Main package
│   ├── __init__.py               # Version, __all__ (48 public names)
│   ├── models.py                 # 17 data types (enums, Pydantic models)
│   ├── config.py                 # Config models + load_config_file()
│   ├── exceptions.py             # EmbeddyError + 8 subclasses
│   ├── embedding/
│   │   ├── __init__.py
│   │   ├── backend.py            # EmbedderBackend ABC, LocalBackend, RemoteBackend
│   │   └── embedder.py           # Embedder facade (cache, MRL, normalization)
│   ├── chunking/
│   │   ├── __init__.py           # get_chunker() factory
│   │   ├── base.py               # BaseChunker ABC
│   │   ├── python_chunker.py     # AST-based Python chunking
│   │   ├── markdown_chunker.py   # Heading-level markdown splits
│   │   ├── paragraph_chunker.py  # Paragraph-based with merging
│   │   ├── token_window_chunker.py  # Sliding window with overlap
│   │   └── docling_chunker.py    # Docling bridge
│   ├── store/
│   │   ├── __init__.py
│   │   └── vector_store.py       # sqlite-vec + FTS5 store
│   ├── ingest/
│   │   ├── __init__.py
│   │   └── ingestor.py           # Content type detection, hashing, Docling routing
│   ├── pipeline/
│   │   ├── __init__.py
│   │   └── pipeline.py           # Ingest → Chunk → Embed → Store
│   ├── search/
│   │   ├── __init__.py
│   │   └── search_service.py     # Vector, fulltext, hybrid (RRF/weighted)
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py                # create_app() factory
│   │   ├── schemas.py            # Request/response Pydantic models
│   │   └── routes/
│   │       ├── health.py         # GET /health, GET /info
│   │       ├── embed.py          # POST /embed, POST /embed/query
│   │       ├── search.py         # POST /search, POST /search/similar
│   │       ├── ingest.py         # POST /ingest/*, DELETE /ingest/source
│   │       ├── collections.py    # Collection CRUD
│   │       └── chunks.py         # Chunk CRUD
│   ├── client/
│   │   ├── __init__.py
│   │   └── client.py             # EmbeddyClient (async httpx)
│   └── cli/
│       ├── __init__.py
│       └── main.py               # Typer CLI
├── tests/                        # Test suite (519 tests)
├── benchmarks/                   # Performance benchmarks
├── examples/
│   └── wikipedia/                # Wikipedia example (download, ingest, search)
├── docs/                         # Documentation
├── pyproject.toml                # Project metadata, tool config
├── README.md                     # Project overview
└── SPEC.md                       # Technical specification
```

## Development Setup

### Prerequisites

- Python 3.13+
- A CUDA-capable GPU (for local embedding — tests use mocks)

### Nix + devenv (Recommended)

The project uses [devenv](https://devenv.sh/) for reproducible development environments:

```bash
# Enter the development shell (installs all system deps + Python + uv)
devenv shell

# Install Python dependencies
uv sync --all-extras
```

### Manual Setup

```bash
# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with all extras
pip install -e ".[all]"

# Or with uv
uv pip install -e ".[all]"
```

## Running Tests

### Test Configuration

Tests use `pytest` with `pytest-asyncio` (auto mode) and `pytest-cov`. Configuration is in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-q --cov=embeddy --cov-report=term-missing"
testpaths = ["tests", "benchmarks"]
asyncio_mode = "auto"
```

The `asyncio_mode = "auto"` setting means async test functions are automatically recognized — no `@pytest.mark.asyncio` decorator needed.

### Running Specific Tests

```bash
# Run all tests
python -m pytest tests/

# Run a specific test file
python -m pytest tests/test_pipeline.py

# Run a specific test by name
python -m pytest tests/test_search.py -k "test_hybrid_search"

# Run with verbose output
python -m pytest tests/ -v

# Run without coverage
python -m pytest tests/ --no-cov
```

### Coverage

Coverage is collected automatically via `--cov=embeddy`. Current target: 94%.

```bash
# Full coverage report
python -m pytest tests/ --cov-report=html

# View the report
open htmlcov/index.html
```

### Benchmarks

Benchmarks live in `benchmarks/` and are included in the test paths. They use `pytest-benchmark`:

```bash
# Run benchmarks
python -m pytest benchmarks/ --benchmark-only

# Run benchmarks with comparison
python -m pytest benchmarks/ --benchmark-compare
```

## Code Style

### Ruff

Ruff handles both linting and formatting. Configuration:

```toml
[tool.ruff]
line-length = 120
target-version = "py313"
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

Run:

```bash
# Check
ruff check src/

# Fix auto-fixable issues
ruff check src/ --fix

# Format
ruff format src/
```

### Mypy

Strict mode is enabled:

```toml
[tool.mypy]
python_version = "3.13"
packages = ["src/embeddy"]
strict = true
warn_unused_ignores = true
warn_redundant_casts = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
disallow_untyped_calls = true
no_implicit_optional = true
```

Run:

```bash
mypy
```

### General Conventions

- **Line length**: 120 characters
- **Quotes**: Double quotes
- **Indentation**: 4 spaces
- **Type hints**: Required on all function signatures (strict mypy)
- **Docstrings**: Google style, on all public functions and classes
- **Async**: All public APIs are async. Synchronous work uses `asyncio.to_thread()`
- **Imports**: Sorted by ruff (isort rules via `"I"` selector)
- **Pydantic v2**: Use `BaseModel`, `Field`, `field_validator`, `model_validator`

## How to Add a New Chunker

1. **Create the chunker class** in `src/embeddy/chunking/`:

```python
# src/embeddy/chunking/my_chunker.py
from embeddy.chunking.base import BaseChunker
from embeddy.config import ChunkConfig
from embeddy.models import Chunk, IngestResult

class MyChunker(BaseChunker):
    def __init__(self, config: ChunkConfig) -> None:
        super().__init__(config)

    def chunk(self, ingest_result: IngestResult) -> list[Chunk]:
        # Implement chunking logic
        chunks = []
        # ... create Chunk objects ...
        return chunks
```

2. **Register it in the factory** (`src/embeddy/chunking/__init__.py`):

Add the new strategy to the `get_chunker()` function:

```python
def get_chunker(config: ChunkConfig, content_type: ContentType) -> BaseChunker:
    strategy = config.strategy
    if strategy == "auto":
        # Add auto-selection mapping if appropriate
        ...
    elif strategy == "my_strategy":
        from embeddy.chunking.my_chunker import MyChunker
        return MyChunker(config)
```

3. **Add the strategy to config validation** in `src/embeddy/config.py`:

Update the `validate_strategy` validator in `ChunkConfig` to include your new strategy name in the `allowed` set.

4. **Write tests** in `tests/test_chunking.py` or a new test file.

5. **Export** from `src/embeddy/__init__.py` if the chunker should be part of the public API.

## How to Add a New Route

1. **Create the route module** in `src/embeddy/server/routes/`:

```python
# src/embeddy/server/routes/my_route.py
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1", tags=["my-feature"])

@router.get("/my-endpoint")
async def my_endpoint(request: Request):
    # Access shared deps from app.state
    store = request.app.state.store
    return {"status": "ok"}
```

2. **Add request/response schemas** to `src/embeddy/server/schemas.py` if needed.

3. **Register the router** in `src/embeddy/server/app.py`:

```python
from embeddy.server.routes.my_route import router as my_router
app.include_router(my_router)
```

4. **Write tests** — the FastAPI test client is available via fixtures.

5. **Add the endpoint to `EmbeddyClient`** if it should be accessible remotely.

## How to Add a New Config Field

1. **Add the field** to the appropriate config model in `src/embeddy/config.py`:

```python
class StoreConfig(BaseModel):
    # Existing fields...
    my_new_field: int = Field(default=42, description="Description of the field.")

    @field_validator("my_new_field")
    @classmethod
    def validate_my_new_field(cls, value: int) -> int:
        if value < 0:
            raise ValueError("my_new_field must be non-negative")
        return value
```

2. **Add environment variable support** if it belongs to `EmbedderConfig` — add the `EMBEDDY_*` env var parsing in `EmbedderConfig.from_env()`.

3. **Use the field** in the relevant layer.

4. **Write tests** covering the default value, validation, and env var parsing (if applicable).

5. **Document** in the config file examples in `docs/USER_GUIDE.md`.

## Versioning

The version is maintained in two places that must stay in sync:

- `src/embeddy/__init__.py`: `__version__ = "X.Y.Z"`
- `pyproject.toml`: `version = "X.Y.Z"`

Convention: `major.minor.patch` — increment patch for bug fixes and docs, minor for new features, major for breaking changes.

## Git Workflow

- **Branch**: Work on `main` (or feature branches for larger changes)
- **Tags**: Each release gets a `vX.Y.Z` tag
- **Commits**: Concise, descriptive commit messages. Prefix with the phase or feature area when doing multi-phase work (e.g. "Phase 12: Documentation overhaul")
- **Tests**: All tests must pass before committing
- **Push**: `git push origin main --tags` to push commits and tags together
