# Remora User Guide

## Table of Contents

1. Getting Started
2. Configuration
3. Bundle Authoring
4. Tool Script Development
5. Virtual Agents
6. Web UI
7. LSP Integration
8. Troubleshooting

## 1. Getting Started

### What Remora Does

Remora turns discovered code elements into autonomous agents. It continuously watches your codebase, projects nodes into a graph, and runs agent turns in response to events.

High-level loop:

1. Discover files and code elements.
2. Materialize nodes/edges in SQLite.
3. Emit events (discovery, edits, messages).
4. Route matching events to actor inboxes.
5. Execute agent turns with tools and model calls.
6. Stream updates to the web UI and editor integrations.

### Prerequisites

- Python 3.13+
- A model endpoint compatible with the configured `model_base_url`
- Tree-sitter language/query assets that match your configured languages

### Install

From this repository:

```bash
pip install -e .
```

### Quick Start

From your project root:

```bash
remora start
```

Useful flags:

```bash
remora start --port 8080 --bind 127.0.0.1
remora start --no-web
remora start --log-level DEBUG --log-events
remora start --lsp
```

Explore discovered nodes:

```bash
remora discover
```

### Runtime Files

By default Remora stores runtime artifacts in `.remora/`:

- `.remora/remora.db`: graph + event store
- `.remora/remora.log`: rotating runtime logs
- `.remora/agents/*`: per-agent workspaces

## 2. Configuration

### Config File Discovery

Remora loads `remora.yaml` via upward directory search (current directory, then parents). You can also pass `--config`.

### Key Fields

Project/discovery:

- `project_path`: logical project root label
- `discovery_paths`: paths to scan (supports relative and absolute)
- `discovery_languages`: optional language allowlist
- `language_map`: extension -> language mapping
- `query_search_paths`: tree-sitter query directories

Bundles:

- `bundle_search_paths`: bundle search directories (first match wins by path order)
- `bundle_overlays`: node type -> bundle name mapping

LLM:

- `model_base_url`
- `model_default`
- `model_api_key`
- `timeout_s`
- `max_turns`

Agent runtime:

- `workspace_root`
- `max_concurrency`
- `max_trigger_depth`
- `trigger_cooldown_ms`
- `actor_inbox_max_items`
- `actor_inbox_overflow_policy` (`drop_new`, `drop_oldest`, `reject`)
- `chat_message_max_chars`
- `conversation_history_max_entries`
- `conversation_message_max_chars`

Workspace behavior:

- `workspace_ignore_patterns`
- `virtual_agents`

### Environment Variables

Prefer setting runtime values in `remora.yaml`.

For environment-specific values, use shell-style expansion in YAML (`${VAR:-default}`),
which is expanded at config load time.

### Shell-Style Expansion

YAML supports `${VAR:-default}` expansion. Example:

```yaml
model_api_key: "${OPENAI_API_KEY:-}"
model_default: "${REMORA_MODEL:-Qwen/Qwen3-4B-Instruct-2507-FP8}"
```

## 3. Bundle Authoring

### Bundle Layout

A bundle is a directory discoverable via `bundle_search_paths` with:

- `bundle.yaml`
- optional `tools/*.pym`

Example:

```text
bundles/
  code-agent/
    bundle.yaml
    tools/
      rewrite_self.pym
      scaffold.pym
```

### Common `bundle.yaml` Fields

- `name`
- `system_prompt` or `system_prompt_extension`
- `prompts.chat`
- `prompts.reactive`
- `model`
- `max_turns`

### Overlay Resolution

`bundle_overlays` maps node types (like `function`, `class`, `directory`) to bundle names.

At provisioning time Remora layers:

1. `bundles/system`
2. mapped role bundle (if present)

This means system tools/prompts are always available unless explicitly overridden.

## 4. Tool Script Development

### Grail Script Basics

Tool scripts are `.pym` files loaded by Grail.

Typical pattern:

```python
from grail import Input, external

node_id: str = Input("node_id")

@external
async def graph_get_node(target_id: str) -> dict: ...

node = await graph_get_node(node_id)
result = node.get("name", "unknown") if node else "missing"
result
```

### Inputs and Externals

- Use `Input()` for typed tool parameters.
- Use `@external` to declare functions provided by `TurnContext`.
- Final expression is returned as tool output.

### Tool Discovery

At runtime, tools are loaded from `_bundle/tools/*.pym` in each agent workspace.

## 5. Virtual Agents

Virtual agents are declared in `remora.yaml` and materialized as nodes of type `virtual`.

Example:

```yaml
virtual_agents:
  - id: "test-agent"
    role: "test-agent"
    subscriptions:
      - event_types: ["node_changed", "node_discovered"]
        path_glob: "tests/**"
```

Subscription fields:

- `event_types`
- `from_agents`
- `to_agent`
- `path_glob`

Use virtual agents for cross-cutting behaviors (quality checks, release coordination, triage).

## 6. Web UI

The web UI includes:

- Live graph view of nodes and edges
- Companion cursor panel
- Per-node chat
- Event stream view
- Conversation history panel (active actors)
- Timeline panel for chronological event flow

Endpoints used by the UI include:

- `GET /api/nodes`
- `GET /api/edges`
- `POST /api/chat`
- `GET /api/health`
- `GET /api/nodes/{node_id}/conversation`
- `GET /sse`

Runtime limits:

- `POST /api/chat` returns `413` when `message` exceeds `chat_message_max_chars`.
- `GET /api/nodes/{node_id}/conversation` clips history to the most recent
  `conversation_history_max_entries` items and truncates each message content to
  `conversation_message_max_chars`.

## 7. LSP Integration

### Embedded Mode

Start with runtime:

```bash
remora start --lsp
```

This shares the runtime `NodeStore`/`EventStore` with LSP.

### Standalone Mode

```bash
remora lsp
```

Standalone mode opens stores from `.remora/remora.db`.

### LSP Features

- CodeLens showing Remora node status
- Hover with node metadata
- `didOpen`/`didSave` emitting content-change events

## 8. Troubleshooting

### No Nodes Discovered

- Verify `discovery_paths` exist.
- Confirm `language_map` includes your file extensions.
- Run `remora discover` and inspect output.

### Web UI Not Updating

- Confirm `/sse` is reachable.
- Check `.remora/remora.log` for runtime or model errors.
- Verify actor subscriptions exist in DB.

### Model Request Failures

- Check `model_base_url`, key, and model name.
- Use `--log-level DEBUG --log-events` for deeper traces.

### LSP Not Showing Data

- Ensure Remora DB exists (`.remora/remora.db`).
- Confirm editor client is connected to the correct LSP process.

### Database/State Inspection

Use SQLite tooling against `.remora/remora.db` to inspect:

- `nodes`
- `edges`
- `events`
- `subscriptions`
