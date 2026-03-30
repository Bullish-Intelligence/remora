# Event Semantics

Reference for Remora event envelopes, event types, error payload guarantees, and API/SSE querying patterns.

## Table of Contents

1. Envelope Format
- Stable top-level shape used by API responses and SSE payload data.

2. Event Type Reference
- Full list of `EventType` identifiers and payload fields.

3. Error Field Contracts
- Structured failure fields for tool and turn events.

4. Querying Events Over HTTP
- `/api/events` filters and response behavior.

5. SSE Stream Contract
- Replay, resume, and live streaming semantics.

6. Scripting Example
- Polling and filtering for review-oriented automations.

## 1. Envelope Format

All Remora events are represented as:

```json
{
  "event_type": "snake_case_id",
  "timestamp": 1710000000.123,
  "correlation_id": "optional-correlation-id",
  "tags": ["optional", "labels"],
  "payload": {}
}
```

Field semantics:
- `event_type`: stable string identifier from `EventType`.
- `timestamp`: unix timestamp (float seconds).
- `correlation_id`: causal chain identifier, optional but propagated when present.
- `tags`: event labels for filtering/routing context.
- `payload`: event-specific fields.

## 2. Event Type Reference

This table mirrors `remora.core.model.types.EventType` and payload models in `remora.core.events.types`.

| Event Type | Payload Fields |
|---|---|
| `agent_start` | `agent_id`, `node_name` |
| `agent_complete` | `agent_id`, `result_summary`, `full_response`, `user_message` |
| `agent_error` | `agent_id`, `error`, `error_class`, `error_reason` |
| `agent_message` | `from_agent`, `to_agent`, `content` |
| `node_discovered` | `node_id`, `node_type`, `file_path`, `name` |
| `node_removed` | `node_id`, `node_type`, `file_path`, `name` |
| `node_changed` | `node_id`, `old_hash`, `new_hash`, `file_path` |
| `content_changed` | `path`, `change_type`, `agent_id`, `old_hash`, `new_hash` |
| `human_input_request` | `agent_id`, `request_id`, `question`, `options` |
| `human_input_response` | `agent_id`, `request_id`, `response` |
| `rewrite_proposal` | `agent_id`, `proposal_id`, `files`, `reason` |
| `rewrite_accepted` | `agent_id`, `proposal_id` |
| `rewrite_rejected` | `agent_id`, `proposal_id`, `feedback` |
| `model_request` | `agent_id`, `model`, `tool_count`, `turn` |
| `model_response` | `agent_id`, `response_preview`, `duration_ms`, `tool_calls_count`, `turn` |
| `tool_result` | `agent_id`, `tool_name`, `result_summary` |
| `remora_tool_call` | `agent_id`, `tool_name`, `arguments_summary`, `turn` |
| `remora_tool_result` | `agent_id`, `tool_name`, `is_error`, `error_class`, `error_reason`, `duration_ms`, `output_preview`, `turn` |
| `turn_complete` | `agent_id`, `turn`, `tool_calls_count`, `errors_count`, `error_summary` |
| `turn_digested` | `agent_id`, `digest_summary`, `has_reflection`, `has_links` |
| `custom` | arbitrary object payload |
| `cursor_focus` | `file_path`, `line`, `character`, `node_id`, `node_name`, `node_type` |

Notes:
- Optional fields may be absent/empty depending on event origin.
- `tool_result` is a legacy event type; runtime turn instrumentation generally emits `remora_tool_*`.

## 3. Error Field Contracts

### `remora_tool_result`

When `is_error` is `true`:
- `error_class` is populated from explicit tool metadata or inferred from output.
- `error_reason` contains a concise human-readable reason (first error line, bounded length).
- If no class can be inferred, runtime defaults to `ToolError`.

### `agent_error`

When turn execution fails in runtime:
- `error` carries full exception text.
- `error_class` is set from the exception class name.
- `error_reason` is the first line of `error`.

### `turn_complete`

When `errors_count > 0`:
- `error_summary` is expected to be populated.
- Runtime synthesizes it from seen tool error classes if upstream summary is empty.

## 4. Querying Events Over HTTP

Endpoint:
- `GET /api/events`

Query params:
- `limit`: `1..500` (default `50`).
- `event_type`: optional exact event type filter.
- `correlation_id`: optional exact correlation filter.

Error response for invalid `limit`:

```json
{
  "error": "invalid_limit",
  "message": "limit must be an integer between 1 and 500"
}
```

Successful response: array of event envelopes (newest first).

Examples:

```bash
curl -sS "http://127.0.0.1:8080/api/events?limit=25"
curl -sS "http://127.0.0.1:8080/api/events?event_type=agent_error&limit=50"
curl -sS "http://127.0.0.1:8080/api/events?correlation_id=test-123&limit=100"
```

## 5. SSE Stream Contract

Endpoint:
- `GET /sse`

Behavior:
- Streams live events as SSE frames.
- `event:` is set to the event type.
- `data:` is a JSON event envelope.

Replay and resume:
- `?replay=<N>` replays up to `N` recent events before live stream (`N <= 500`).
- `Last-Event-ID` header replays events strictly after that event ID.
- `?once=true` returns replay output and closes.

Operational notes:
- Includes initial keepalive comment (`: connected`).
- On shutdown, server emits `: server-shutdown` comment before close.

## 6. Scripting Example

Simple poller that alerts on review-related failures:

```python
import requests

resp = requests.get(
    "http://127.0.0.1:8080/api/events",
    params={"event_type": "remora_tool_result", "limit": 100},
    timeout=10,
)
resp.raise_for_status()
for event in resp.json():
    payload = event.get("payload", {})
    if payload.get("tool_name") == "review_diff" and payload.get("is_error"):
        print(
            "review_diff failed:",
            payload.get("error_class", ""),
            payload.get("error_reason", ""),
            "corr=",
            event.get("correlation_id"),
        )
```

For live automation, consume `GET /sse` and maintain the last seen `id` for resume via `Last-Event-ID`.
