# Architecture

This document describes the internal architecture of `structured-agents` and how the major subsystems interact.

## High-Level Overview

`structured-agents` provides a core agent loop that repeatedly:

1. Formats messages and tool schemas for a model via `ModelAdapter`.
2. Sends a chat completion request to an OpenAI-compatible API via `LLMClient`.
3. Parses tool calls from the model response.
4. Executes tools directly through the `Tool` protocol.
5. Updates history and emits observer events.

The system is intentionally modular. Each subsystem is replaceable and focused.

## Core Modules

### Agent Kernel (`structured_agents.kernel`)

- Orchestrates the agent loop.
- Manages history trimming and concurrency limits (`max_history_messages`, `max_concurrency`).
- Delegates formatting/parsing to `ModelAdapter`.
- Executes tools via the `Tool` protocol.
- Emits observer events for visibility and diagnostics.

### Model Adapter (`structured_agents.models`)

- Formats messages and tool schemas for the target model.
- Parses model responses into tool calls.
- Optionally carries a `ConstraintPipeline` for structured outputs.

### Client (`structured_agents.client`)

- `LLMClient` defines the client interface.
- `OpenAICompatibleClient` implements the OpenAI/vLLM request surface.
- `build_client` provides a public factory for client reuse.

### Tools (`structured_agents.tools.protocol`)

- `Tool` is a protocol: every tool provides a schema and an async execute method.
- Kernels keep an internal tool map for dispatch and error reporting.

### Grammar (`structured_agents.grammar`)

- `DecodingConstraint` captures optional structured output configuration.
- `ConstraintPipeline` builds `structured_outputs` payloads for the API.
- `StructuredOutputModel` is the Pydantic base class for JSON schema outputs.

### Observers (`structured_agents.events`)

- Event system for tooling and telemetry.
- `CompositeObserver` fans out events.
- `NullObserver` is the default no-op implementation.

## Data Flow

```
Initial Messages + Tool Schemas
        │
        ▼
  ModelAdapter → formatted messages/tools
        │
        ▼
  LLMClient → CompletionResponse
        │
        ▼
  ModelAdapter → content + ToolCalls
        │
        ▼
  Tool execution → ToolResults
        │
        ▼
  History + Observer Events → RunResult
```

## Type System and Contracts

- Core dataclasses live in `structured_agents.types` (`Message`, `ToolCall`, `ToolResult`, `RunResult`).
- Protocols define extensibility points for tools, observers, and clients.
- `StructuredOutputModel` uses Pydantic for JSON schema generation.

## Error Handling

- `StructuredAgentsError` is the base exception.
- `KernelError` is raised for API call failures or invalid request state.
- Tool exceptions are captured and returned as `ToolResult` with `is_error=True`.

## Event Lifecycle

Events are emitted in this order per turn:

1. `KernelStartEvent` (once at run start)
2. `ModelRequestEvent` (pre-step summary)
3. `ModelRequestEvent` (per API request in `step`)
4. `ModelResponseEvent`
5. `ToolCallEvent` (per tool)
6. `ToolResultEvent` (per tool; order follows completion when concurrency > 1)
7. `TurnCompleteEvent`
8. `KernelEndEvent` (once at run end)

## Extensibility Points

- Add new response parsing behavior by implementing a `ResponseParser` and wiring it into a `ModelAdapter`.
- Add new tool integrations by implementing the `Tool` protocol.
- Add new client implementations by implementing `LLMClient`.
- Add new observers for logging, tracing, or UI integration.
- Add new structured output models by subclassing `StructuredOutputModel`.

## Dependencies

- `openai`: used by the OpenAI-compatible client.
- `vllm`: optional runtime dependency for local OpenAI-compatible serving.
- `grail`: required for `.pym` execution in Grail tool backends.
- `xgrammar`: required for grammar-constrained decoding (optional).

## Grammar-Constrained Decoding

Grammar constraints are optional. When `DecodingConstraint` is provided, the `ModelAdapter` carries a `ConstraintPipeline`, and `AgentKernel.step()` calls `constraint_pipeline.constrain(resolved_tools)` to build the `extra_body` payload. When no constraint is provided, the system relies on native tool calling.

### Configuration

```python
from structured_agents.grammar import DecodingConstraint, StructuredOutputModel

class ExampleOutput(StructuredOutputModel):
    value: int
    note: str

constraint = DecodingConstraint(
    strategy="json_schema",
    schema_model=ExampleOutput,
)
```

### Supported Strategies

- **`json_schema`**: Emits `{"structured_outputs": {"json": <schema>}}` for vLLM’s structured outputs. This is the recommended constraint path.
- **`structural_tag`**: Emits a legacy structural tag payload for tool tags. This is experimental and must be explicitly enabled.
- **`ebnf`**: Reserved for advanced usage. No payload is emitted unless a supported strategy is selected.

### Response Parsing

Tool calls are parsed from the API `tool_calls` field when present. Content-based parsing is a fallback for legacy XML formats.

## Related Documents

- `GRAMMAR_INTEGRATION_REPORT.md`: structured output integration analysis.
- `V033_GRAMMAR_REFACTORING_GUIDE.md`: step-by-step refactor guide.
