# Remora v2

Remora is a reactive agent substrate where discovered nodes (functions, classes,
methods, markdown sections, TOML tables, directories, virtual agents) are
represented and executed as autonomous agents.

Key capabilities in this refactor:
- Multi-language tree-sitter discovery (`.py`, `.md`, `.toml`) with query overrides
- Incremental `FileReconciler` for startup scan + continuous add/change/delete sync
- Event-driven runner with bundle-in-workspace tooling and proposal approval flow
- Web graph surface with SSE streaming
- Typer CLI (`remora start`, `remora discover`, `remora index`, `remora lsp`)
- Optional LSP adapter for code lens / hover / save/open event forwarding (start with `remora start --lsp`)

Configuration highlights in `remora.yaml`:
- `discovery_paths`: directories/files to scan
- `language_map`: extension -> language mapping for discovery
- `query_search_paths`: override directories for `*.scm` tree-sitter queries

## Testing Profiles

Run all commands via `devenv shell -- ...`.

- Deterministic CI/local core checks (no environment-dependent E2E):
  - `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -m "not acceptance and not real_llm" -q`
- Fast actor-level real-vLLM checks (kept for quick signal):
  - `devenv shell -- env REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' pytest tests/integration/test_llm_turn.py -m real_llm -q -rs`
- Process-boundary acceptance checks:
  - `devenv shell -- pytest tests/acceptance -m acceptance -q -rs`
- Full real-world acceptance with model in the loop:
  - `devenv shell -- env REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' pytest tests/acceptance -m "acceptance and real_llm" -q -rs`

Acceptance tests use strict polling timeouts and deterministic identifiers/correlation checks to reduce flakiness.
