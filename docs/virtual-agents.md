# Virtual Agents

Operational guide for declarative virtual agents, reactive execution flow, and bundle/tool contracts.

## Table of Contents

1. Overview
- What virtual agents are and how they differ from file-backed nodes.

2. Configuration Model
- `virtual_agents` schema and subscription pattern fields.

3. Reference Virtual Agents
- Review-agent and companion patterns used in real deployments.

4. Reactive Turn Lifecycle
- Event persistence, subscription matching, actor execution, and emitted events.

5. Tool Contracts
- Inputs, externals, and expected behavior for default review/companion tools.

6. Loop Guards and Correlation Safety
- How recursion and repeated reactive turns are bounded.

7. Customization Workflow
- How to add or replace virtual roles safely.

## 1. Overview

Virtual agents are graph nodes with `node_type: virtual` that are declared in config instead of discovered from source files.

Key properties:
- Materialized by `VirtualAgentManager` during reconcile cycles.
- Persisted in the same `nodes` table as file-backed nodes.
- Triggered through the same event/subscription system as other agents.
- Provisioned with the same bundle layering model (`system` + role bundle).

Use virtual agents for cross-cutting concerns like review, observation, triage, or release checks that are not tied to one file.

## 2. Configuration Model

`remora.yaml` supports `virtual_agents` entries with:
- `id`: stable node ID.
- `role`: bundle name to provision.
- `subscriptions`: declarative filters.

Supported subscription fields:
- `event_types`: list of snake_case event IDs (`content_changed`, `turn_digested`, etc.).
- `from_agents`: only events emitted by listed agents.
- `to_agent`: direct-message targeting.
- `path_glob`: file/path filter.
- `tags`: event tag intersection filter.

Example:

```yaml
virtual_agents:
  - id: "review-agent"
    role: "review-agent"
    subscriptions:
      - event_types: ["content_changed"]
        path_glob: "src/**"

  - id: "companion"
    role: "companion"
    subscriptions:
      - event_types: ["turn_digested"]
```

Notes:
- Every virtual agent also gets a direct-message subscription (`to_agent=<id>`).
- Changing role/subscription config updates node hash and triggers re-sync.

## 3. Reference Virtual Agents

Common deployment pattern:
- `review-agent`: reacts to `content_changed` and emits review findings.
- `companion`: reacts to `turn_digested` and maintains project-level activity state.

Bundle definitions live at:
- `src/remora/defaults/bundles/review-agent/bundle.yaml`
- `src/remora/defaults/bundles/companion/bundle.yaml`

These bundles include explicit guardrails:
- Stop if required tool calls fail.
- Avoid repeated tool retries in a single reactive turn.
- Keep outputs bounded.

## 4. Reactive Turn Lifecycle

1. Event is persisted into `events` via `EventStore.append`.
2. `TriggerDispatcher` resolves matching agent IDs from `SubscriptionRegistry`.
3. `ActorPool` routes each event into per-agent inbox queues.
4. `Actor` dequeues event, applies `TriggerPolicy`, and executes one turn.
5. `AgentTurnExecutor` loads workspace bundle/tools, calls model/tools, emits events.
6. Outbox persists translated events (`agent_start`, `remora_tool_result`, `turn_complete`, `agent_complete`, etc.).

For virtual agents, lifecycle is identical to file-backed nodes after trigger dispatch.

## 5. Tool Contracts

### Review-Agent Tools

`review_diff.pym`
- Inputs: `node_id`.
- Externals: `graph_get_node`, `kv_get`, `kv_set`.
- Behavior:
- Handles missing node (`graph_get_node -> None`) without raising.
- Caches previous source snapshot and reports bounded diff preview.

`list_recent_changes.pym`
- Inputs: none.
- Externals: `graph_list_nodes`.
- Behavior:
- Summarizes discovered nodes with bounded item count and output size.

`submit_review.pym`
- Inputs: `node_id`, `finding`, `severity`, `notify_user`.
- Externals: `send_message`.
- Behavior:
- Validates non-empty `node_id`.
- Handles unexpected `send_message` response shapes safely.

### Companion Tool

`aggregate_digest.pym`
- Inputs: `agent_id`, `summary`, `tags`, `insight`.
- Externals: `kv_get`, `kv_set`, `my_correlation_id`.
- Behavior:
- Normalizes malformed KV payloads before update.
- Persists bounded activity log, tag frequency, per-agent summary, and optional insights.
- Carries correlation IDs into stored digest records.

## 6. Loop Guards and Correlation Safety

Reactive safety is enforced in `TriggerPolicy`:
- `trigger_cooldown_ms`: minimum delay between triggers.
- `max_trigger_depth`: recursion/depth ceiling per `correlation_id`.
- `max_reactive_turns_per_correlation`: cap on repeated reactive turns for the same correlation (default `3`).

`Outbox` propagates `correlation_id` across emitted turn events. This keeps causality visible and lets operators trace a reactive chain in `/api/events` and `/sse`.

## 7. Customization Workflow

1. Add or edit `virtual_agents` in `remora.yaml`.
2. Create/update corresponding role bundle under `bundles/` (or defaults override path).
3. Keep subscriptions narrow (`event_types`, `path_glob`, tags) to avoid noisy fan-out.
4. Keep tool outputs bounded and treat externals as untrusted inputs.
5. Validate with:
- `devenv shell -- remora start`
- `GET /api/events?event_type=...`
- `GET /sse?replay=50`

If the role emits secondary events, verify it does not self-trigger indefinitely; tune `runtime.max_reactive_turns_per_correlation` when needed.
