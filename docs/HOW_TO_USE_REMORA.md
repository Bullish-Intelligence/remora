# How To Use Remora

This guide is a practical one-stop reference for developers building applications with Remora.

## Table of Contents

1. What Remora Is
- What problems Remora solves, and when to use it.

2. Core Concepts You Need First
- Node graph model, event model, actor execution model, and workspaces.

3. Installation and Runtime Prerequisites
- Python/dependencies, model endpoint expectations, optional extras (LSP/search).

4. Quick Start (5 Minutes)
- Minimal config and first successful `remora start` + `remora discover` run.

5. Running Remora in Practice
- CLI commands (`start`, `discover`, `index`, `lsp`) and common flag patterns.

6. Configuration Reference (Developer-Focused)
- The config keys you will use most, with correct current field names and behavior.

7. Building Agents with Bundles
- Bundle structure, overlay resolution, and practical bundle design patterns.

8. Writing Tool Scripts (`.pym`) That Work Reliably
- Grail script structure, externals usage, and common implementation pitfalls.

9. Event-Driven Application Patterns
- Subscription design, message routing, reflection loops, and avoiding event mismatches.

10. Virtual Agents for Cross-Cutting Behaviors
- How to add test/review/observer roles without binding to a file-backed node.

11. Web APIs and UI Integration
- Key REST/SSE endpoints, offline UI behavior, and integration patterns.

12. LSP Integration
- Setup flow, diagnostics, and embedded vs standalone usage.

13. Search/Index Integration
- Setup flow, diagnostics, and indexing/search usage.

14. Programmatic Embedding (Using Remora from Python)
- How to start/stop runtime services from your own Python application.

15. Testing and Verification Workflow
- Practical local checks and test profiles that match repo conventions.

16. Operational Guidance
- Logging, state files, performance limits, and safe production defaults.

17. Troubleshooting Playbook
- Fast diagnosis for no discovery, no triggers, no SSE updates, and model/tool failures.

18. End-to-End Build Blueprint
- Recommended sequence for building a real Remora-powered application from scratch.

## 1. What Remora Is

Remora is an event-driven runtime for turning discovered project elements into autonomous agents.

In practical terms, Remora gives you:
- A projected graph of nodes (functions, classes, methods, markdown sections, TOML tables, directories, virtual agents).
- An append-only event log and in-memory event routing.
- Actor-based execution so each node can react to events, call tools, and coordinate with other agents.
- A web API/SSE surface (and optional LSP) for integrating into your app UX.

Use Remora when you want application behavior to emerge from event-triggered, tool-using agents tied to real project structure.

## 2. Core Concepts You Need First

### Node Graph
- Nodes are persisted in SQLite (`nodes` table) with metadata like `node_id`, `node_type`, `file_path`, `text`, `status`, and `role`.
- Edges (`edges` table) represent relationships (for example, containment).

### Events
- Events are persisted in SQLite (`events` table) and then dispatched.
- Event type IDs are snake_case strings (for example: `node_changed`, `agent_message`, `turn_digested`).
- Subscription matching is pattern-based (`event_types`, `from_agents`, `to_agent`, `path_glob`, `tags`).
- Full contract reference: `docs/event-semantics.md`.

### Actors
- Each active node can have an actor with an inbox.
- Actors process triggers sequentially, enforce cooldown/depth constraints, run model/tool turns, and emit events.

### Workspaces and Bundles
- Every agent gets a workspace under `.remora/agents/...`.
- Bundles are layered into `_bundle/` (typically `system` + role bundle) and provide prompts and `.pym` tools.

## 3. Installation and Runtime Prerequisites

### Required
- Python `>=3.13`
- A reachable model endpoint compatible with your configured `model_base_url`

### Install

```bash
devenv shell -- uv sync --extra dev
```

For editable local use:

```bash
devenv shell -- pip install -e .
```

### Optional Extras
- LSP support: install `remora[lsp]` dependencies (`pygls`, `lsprotocol`).
- Semantic search:
  - Remote mode: `remora[search]` + running embeddy server.
  - Local mode: `remora[search-local]` for in-process embedding/vector stack.

### Runtime Outputs
By default, runtime state lives under `.remora/`:
- `.remora/remora.db`
- `.remora/remora.log`
- `.remora/agents/*`

## 4. Quick Start (5 Minutes)

Create `remora.yaml` at your project root:

```yaml
project_path: "."
discovery_paths:
  - "src/"

language_map:
  ".py": "python"
  ".md": "markdown"
  ".toml": "toml"

query_search_paths:
  - "queries/"
  - "@default"

bundle_search_paths:
  - "bundles/"
  - "@default"

bundle_overlays:
  function: "code-agent"
  class: "code-agent"
  method: "code-agent"
  directory: "directory-agent"

model_base_url: "http://localhost:8000/v1"
model_default: "Qwen/Qwen3-4B"
model_api_key: "${OPENAI_API_KEY:-}"
```

Start runtime:

```bash
devenv shell -- remora start
```

In another terminal, verify discovery:

```bash
devenv shell -- remora discover
```

Open web UI:
- `http://127.0.0.1:8080`

## 5. Running Remora in Practice

### `remora start`
Use for normal runtime execution.

Common examples:

```bash
devenv shell -- remora start
devenv shell -- remora start --port 8081 --bind 0.0.0.0
devenv shell -- remora start --no-web
devenv shell -- remora start --log-level DEBUG --log-events
devenv shell -- remora start --lsp
```

### `remora discover`
Run discovery once and print node summaries.

```bash
devenv shell -- remora discover
devenv shell -- remora discover --project-root /path/to/project
```

### `remora index`
Index files for semantic search.

```bash
devenv shell -- remora index
devenv shell -- remora index --collection code --include "*.py" --exclude ".venv/**"
```

### `remora lsp`
Run standalone LSP server using `.remora/remora.db`.

```bash
devenv shell -- remora lsp
```

## 6. Configuration Reference (Developer-Focused)

Most-used fields:

- Discovery:
  - `discovery_paths`
  - `discovery_languages`
  - `language_map`
  - `query_search_paths`
  - `workspace_ignore_patterns`

- Bundles:
  - `bundle_search_paths`
  - `bundle_overlays`
  - `bundle_rules`

- Runtime controls:
  - `max_concurrency`
  - `max_trigger_depth`
  - `trigger_cooldown_ms`
  - `actor_inbox_max_items`
  - `actor_inbox_overflow_policy` (`drop_new`, `drop_oldest`, `reject`)

- Model/infra:
  - `model_base_url`
  - `model_api_key`
  - `model_default`
  - `timeout_s`

- UX/safety limits:
  - `chat_message_max_chars`
  - `conversation_history_max_entries`
  - `conversation_message_max_chars`
  - `broadcast_max_targets`

- Optional features:
  - `search` block
  - `virtual_agents`

### Config Key Pitfalls to Avoid

- Use `query_search_paths`, not `query_paths`.
- Use `bundle_search_paths`, not `bundle_root`.
- For subscriptions, event type values should be snake_case IDs (`node_changed`), not class names (`NodeChangedEvent`).

### Environment Values

Preferred pattern is YAML expansion:

```yaml
model_api_key: "${OPENAI_API_KEY:-}"
model_default: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"
```

This is expanded during config loading and is reliable for nested config fields.

## 7. Building Agents with Bundles

### Bundle Layout
A bundle is found via `bundle_search_paths` and usually includes:

```text
<bundle-name>/
  bundle.yaml
  tools/
    *.pym
```

### `bundle.yaml` Fields You Will Actually Use
- `system_prompt`
- `system_prompt_extension`
- `prompts.chat`
- `prompts.reactive`
- `model`
- `max_turns`
- `self_reflect`
- `externals_version`

### Layering Behavior
For each node, Remora typically provisions:
1. `system` bundle
2. role bundle (from `bundle_overlays` or `bundle_rules`)

This means system tools are available unless overwritten.

### Externals Compatibility
- Runtime externals version is currently `2`.
- If a bundle declares `externals_version` greater than runtime, the turn fails with `IncompatibleBundleError`.
- Keep custom bundles pinned to the runtime contract version.

## 8. Writing Tool Scripts (`.pym`) That Work Reliably

### Minimal Pattern

```python
from grail import Input, external

node_id: str = Input("node_id")

@external
async def graph_get_node(target_id: str) -> dict: ...

node = await graph_get_node(node_id)
result = node.get("name", "missing") if node else "missing"
result
```

### Practical Rules
- Declare all tool inputs with `Input(...)`.
- Declare every runtime capability you call with `@external`.
- Return concise structured output when possible.
- Use snake_case event names when emitting/subscribing.

### Frequently Used Externals
- Files: `read_file`, `write_file`, `list_dir`, `search_content`
- KV: `kv_get`, `kv_set`
- Graph: `graph_get_node`, `graph_query_nodes`, `graph_get_children`
- Events: `event_emit`, `event_subscribe`, `event_get_history`
- Comms: `send_message`, `broadcast`, `request_human_input`, `propose_changes`
- Identity: `my_node_id`, `my_correlation_id`, `get_node_source`

### Common Failure Modes
- Using stale event names (`NodeChangedEvent` instead of `node_changed`).
- Assuming an external exists that is not in `TurnContext`.
- Writing to `_bundle/` and expecting those files to be treated as user code changes.

## 9. Event-Driven Application Patterns

### Pattern A: Direct Chat to a Node
- User posts to `POST /api/chat` with `node_id` and `message`.
- Runtime emits `agent_message` from `user` to target node.
- Node actor runs and should respond via `send_message(..., to_node_id="user")`.

### Pattern B: File-Scoped Reactivity
- Subscribe node/virtual agent to `node_changed` + `path_glob`.
- When reconciler detects hash changes, events trigger only relevant agents.

### Pattern C: Controlled Rewrite Flow
- Agent writes proposed changes into workspace.
- Agent calls `propose_changes` to emit `rewrite_proposal` and set `awaiting_review`.
- Human accepts/rejects through proposal APIs.

### Subscription Design Checklist
- Use exact event IDs (snake_case).
- Prefer narrow `path_glob` and tags to avoid noisy triggers.
- Use `to_agent` for direct-message-only behavior.

## 10. Virtual Agents for Cross-Cutting Behaviors

Virtual agents are config-declared nodes (`node_type=virtual`) that are not tied to a source file.

Example:

```yaml
virtual_agents:
  - id: "test-agent"
    role: "test-agent"
    subscriptions:
      - event_types: ["node_changed", "node_discovered"]
        path_glob: "src/**"
```

Use virtual agents for:
- Review pipelines
- Test scaffolding
- Project-level observers
- Release/compliance checks

Design tip:
- Keep virtual roles narrow and explicit; broad subscriptions can overwhelm runtime throughput.
- Detailed architecture and tool contracts: `docs/virtual-agents.md`.

## 11. Web APIs and UI Integration

Key endpoints:
- `GET /api/health`
- `GET /api/nodes`
- `GET /api/edges`
- `GET /api/events`
- `POST /api/chat`
- `GET /api/nodes/{node_id}/conversation`
- `GET /api/nodes/{node_id}/companion`
- `GET /api/proposals`
- `POST /api/proposals/{node_id}/accept`
- `POST /api/proposals/{node_id}/reject`
- `POST /api/search` (when search is enabled and available)
- `GET /sse`

### Offline Web UI
Remora ships vendored graph UI scripts and does not require CDN access.

Static assets:
- `/static/vendor/graphology.umd.min.js`
- `/static/vendor/sigma.min.js`

`src/remora/web/static/index.html` references these local paths directly.

Quick verification:

```bash
curl -sS -I http://127.0.0.1:8080/static/vendor/graphology.umd.min.js
curl -sS -I http://127.0.0.1:8080/static/vendor/sigma.min.js
```

If either request is not `200`:
- Check package/static file install state.
- Verify your runtime serves `src/remora/web/static/`.
- Verify `index.html` script tags still point to `/static/vendor/*`.

### SSE Integration
Use `GET /sse` for live event streaming.

Useful options:
- `?replay=100` to replay recent events first.
- `Last-Event-ID` header to resume from last seen ID.

### Chat Integration Contract
`POST /api/chat` request:

```json
{
  "node_id": "src/app.py::my_func",
  "message": "Explain your behavior"
}
```

Server-side protections:
- Per-IP chat rate limiter.
- `413` when `message` exceeds `chat_message_max_chars`.

## 12. LSP Integration

### LSP Setup

Install optional LSP dependencies:

```bash
devenv shell -- uv sync --extra lsp
```

Sanity check:

```bash
devenv shell -- remora lsp --help
```

If `pygls` is missing, Remora reports:
- install command: `uv sync --extra lsp`
- docs reference: `docs/HOW_TO_USE_REMORA.md#lsp-setup`

### Embedded Mode
Start LSP inside runtime:

```bash
devenv shell -- remora start --lsp
```

### Standalone Mode
Attach to existing `.remora/remora.db`:

```bash
devenv shell -- remora lsp
```

### Exposed Features
- CodeLens with node status
- Hover with node metadata and recent events
- Code actions (open chat panel, trigger agent)
- `didOpen` / `didSave` content-change event emission

## 13. Search/Index Integration

### Search Setup

Install optional search dependencies:

```bash
devenv shell -- uv sync --extra search
```

Enable in `remora.yaml`:

```yaml
search:
  enabled: true
  mode: "remote"
  embeddy_url: "http://localhost:8585"
  timeout: 30.0
  default_collection: "code"
```

Verify API behavior:

```bash
curl -sS -X POST http://127.0.0.1:8080/api/search \
  -H "content-type: application/json" \
  -d '{"query":"actor inbox overflow","top_k":5}'
```

Troubleshooting matrix:

| Symptom | HTTP Code | Cause | Fix |
|---|---:|---|---|
| `search_not_configured` | `501` | Search extra not installed/configured | `devenv shell -- uv sync --extra search` |
| `search_backend_unavailable` | `503` | Embedding backend unreachable | Start/check embeddy and URL |
| `invalid_request` | `400` | Missing/invalid payload fields | Send valid `query`, `top_k`, and `mode` |

Enable search in `remora.yaml`:

```yaml
search:
  enabled: true
  mode: "remote"
  embeddy_url: "http://localhost:8585"
  timeout: 30.0
  default_collection: "code"
```

Index your project:

```bash
devenv shell -- remora index
devenv shell -- remora index --collection code --include "*.py"
```

Use via web API:
- `POST /api/search` with `query`, optional `collection`, `top_k`, `mode`.

Tool-level search externals:
- `semantic_search(...)`
- `find_similar_code(...)`

## 14. Programmatic Embedding (Using Remora from Python)

If you want Remora inside your own app process, use runtime services directly.

Example skeleton:

```python
import asyncio
from pathlib import Path

from remora.core.model.config import load_config
from remora.core.services.container import RuntimeServices
from remora.core.storage.db import open_database


async def main() -> None:
    project_root = Path(".").resolve()
    config = load_config(project_root / "remora.yaml")

    db_path = project_root / config.infra.workspace_root / "remora.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await open_database(db_path)

    services = RuntimeServices(config, project_root, db)
    await services.initialize()

    try:
        # Initial projection
        await services.reconciler.full_scan()

        # Start background loops
        runner_task = asyncio.create_task(services.runner.run_forever())
        reconciler_task = asyncio.create_task(services.reconciler.run_forever())

        await asyncio.gather(runner_task, reconciler_task)
    finally:
        await services.close()


if __name__ == "__main__":
    asyncio.run(main())
```

If you also need HTTP endpoints, build Starlette app with `remora.web.server.create_app(...)` using these same services.

## 15. Testing and Verification Workflow

Run project tooling in repo style:

```bash
devenv shell -- uv sync --extra dev
```

Core deterministic checks:

```bash
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -m "not acceptance and not real_llm" -q
```

Acceptance checks:

```bash
devenv shell -- pytest tests/acceptance -m acceptance -q -rs
```

Real model loop (when endpoint available):

```bash
devenv shell -- env REMORA_TEST_MODEL_URL='http://remora-server:8000/v1' REMORA_TEST_MODEL_NAME='Qwen/Qwen3-4B-Instruct-2507-FP8' pytest tests/integration/test_llm_turn.py -m real_llm -q -rs
```

## 16. Operational Guidance

### Logs and Diagnostics
- Runtime logs: `.remora/remora.log`
- Enable richer trace: `--log-level DEBUG --log-events`

### Throughput and Safety Knobs
- `max_concurrency`: parallel turn ceiling
- `trigger_cooldown_ms`: throttles rapid retriggers
- `max_trigger_depth`: bounds correlation recursion
- `actor_inbox_max_items` + `actor_inbox_overflow_policy`: backpressure behavior
- `send_message_rate_limit` + `send_message_rate_window_s`: anti-spam on tool messaging

### Recommended Starting Defaults
- Keep defaults for first deployment.
- Add targeted virtual agents before broad global ones.
- Narrow subscriptions with `path_glob` and tags.
- Keep rewrite flow human-gated through proposals.

## 17. Troubleshooting Playbook

### No Nodes Discovered
- Check `discovery_paths` exist.
- Verify `language_map` extensions.
- Verify queries exist in `query_search_paths`.
- Run `devenv shell -- remora discover`.

### Agents Not Triggering
- Confirm subscription uses snake_case event IDs.
- Confirm `path_glob` matches actual event `file_path`/`path`.
- Check `subscriptions` table in `.remora/remora.db`.

### Web UI Not Updating
- Check `/sse` connectivity.
- Check `.remora/remora.log` for runtime exceptions.
- Verify events are being appended in `events` table.

### Proposal Accept Writes Wrong Files
- Ensure tool writes use expected workspace path conventions.
- Review proposal diff via proposal endpoints before acceptance.

### Search Unavailable
- Confirm `POST /api/search` status:
  - `501 search_not_configured` -> run `devenv shell -- uv sync --extra search`.
  - `503 search_backend_unavailable` -> fix embeddy connectivity/config.
- Verify `search.enabled: true` in `remora.yaml`.
- Run `devenv shell -- remora index` and inspect errors.

### LSP Shows Nothing
- Ensure `.remora/remora.db` exists and runtime has discovered nodes.
- Ensure LSP deps are installed: `devenv shell -- uv sync --extra lsp`.
- Use embedded mode (`devenv shell -- remora start --lsp`) or standalone (`devenv shell -- remora lsp`).

## 18. End-to-End Build Blueprint

1. Define your product behavior as event flows, not monolithic prompts.
2. Configure discovery/language/query paths and verify with `remora discover`.
3. Design bundles by role (system + focused role overlays).
4. Implement minimal `.pym` tools for each role and verify externals usage.
5. Add virtual agents for cross-cutting workflows (test/review/observer).
6. Start runtime and validate event routing in `/api/events` and `/sse`.
7. Integrate frontend/editor UX through web APIs and optional LSP.
8. Add semantic search only after core flow is stable.
9. Lock in tests (core + acceptance) and tune runtime limits.
10. Promote to production with conservative concurrency and explicit review gates.

---

If you keep three things consistent, most Remora builds are stable:
- Correct config keys (`query_search_paths`, `bundle_search_paths`)
- Correct event IDs (snake_case)
- Correct bundle/tool contract versioning (`externals_version` <= runtime)
