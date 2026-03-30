# How To Use structured-agents

This guide is a one-stop reference for integrating `structured-agents` into your application. It covers core concepts, runtime setup, tool definitions, structured outputs, and best practices for production use.

## Quick Orientation

`structured-agents` is an async-first library that orchestrates:

1. **Model calls** via an OpenAI-compatible client.
2. **Tool calls** parsed from model output.
3. **Tool execution** with structured arguments.
4. **Event emission** for observability.

Native tool calling is the default. Structured output constraints are optional and can be enabled per adapter.

## Requirements

- **Python 3.13+**
- An **OpenAI-compatible API** (vLLM recommended)

Optional extras:

```bash
pip install "structured-agents[grammar]"   # xgrammar for structured outputs
pip install "structured-agents[vllm]"      # vLLM compatibility
```

If you execute Grail `.pym` tools, ensure `grail` is available (installed by default).

## Core Concepts

**Message**
- Represents model input and output.
- `Message(role="user", content="...")`

**ToolSchema**
- JSON schema describing a tool’s parameters.
- Used by the model to construct valid tool calls.

**Tool**
- Protocol with a `schema` property and an async `execute()` method.
- The kernel uses these for tool dispatch.

**ModelAdapter**
- Formats requests and parses responses.
- Carries an optional `ConstraintPipeline` for structured outputs.

**AgentKernel**
- The core loop that sends model requests, runs tools, and aggregates results.

**Agent**
- Higher-level convenience wrapper around `AgentKernel` and `AgentManifest`.

## Minimal End-to-End Example

This example defines a single tool, sends a user message, and lets the model call the tool.

```python
import asyncio
from dataclasses import dataclass
from typing import Any

from structured_agents import (
    AgentKernel,
    Message,
    ModelAdapter,
    QwenResponseParser,
    ToolCall,
    ToolResult,
    ToolSchema,
)
from structured_agents.client import build_client
from structured_agents.tools.protocol import Tool


@dataclass
class GreetTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="greet",
            description="Greet someone",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        name = arguments.get("name", "there")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=f"Hello, {name}!",
            is_error=False,
        )


async def main() -> None:
    tools = [GreetTool()]
    tool_schemas = [tool.schema for tool in tools]

    client = build_client(
        {
            "base_url": "http://localhost:8000/v1",
            "api_key": "EMPTY",
            "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
        }
    )

    adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())
    kernel = AgentKernel(client=client, adapter=adapter, tools=tools)

    result = await kernel.run(
        [Message(role="user", content="Greet Alice")],
        tool_schemas,
        max_turns=3,
    )

    print(result.final_message.content)
    await kernel.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## ModelAdapter and Response Parsing

`ModelAdapter` defines two critical behaviors:

- **Formatting**: preparing messages and tool schemas for the model.
- **Parsing**: extracting tool calls from the model response.

The default `QwenResponseParser` can parse tool calls from the response `tool_calls` field and falls back to legacy XML-style parsing when needed.

## Structured Outputs (Optional)

If you need strict JSON schema responses, enable a `ConstraintPipeline` with a `DecodingConstraint` and `StructuredOutputModel`.

```python
from structured_agents import DecodingConstraint, StructuredOutputModel
from structured_agents.grammar.pipeline import ConstraintPipeline


class StatusOutput(StructuredOutputModel):
    status: str
    detail: str


constraint = DecodingConstraint(
    strategy="json_schema",
    schema_model=StatusOutput,
)

adapter = ModelAdapter(
    name="qwen",
    response_parser=QwenResponseParser(),
    constraint_pipeline=ConstraintPipeline(constraint),
)
```

**Important:** constraints are only attached when you pass tool schemas to the kernel. The `ConstraintPipeline` builds a `structured_outputs` payload which the client sends via `extra_body`.

### Strategy Options

- `json_schema`: recommended for standard schema constraints.
- `structural_tag`: experimental legacy structural tags.
- `ebnf`: reserved for advanced use (no payload emitted unless explicitly supported).

## Agent Convenience Wrapper

`Agent` wraps a kernel and manifest for repeated use:

```python
from structured_agents import Agent, AgentManifest

manifest = AgentManifest(
    name="assistant",
    system_prompt="You are a helpful assistant with tools.",
    agents_dir="./agents",
)

agent = Agent(kernel=kernel, manifest=manifest)
result = await agent.run("Greet Alice")
```

This is helpful when you want a lightweight, reusable agent instance with a fixed system prompt.

## Configuration Tips for vLLM

For Qwen-family models, configure your vLLM server with tool parsing enabled:

- `--tool-call-parser qwen3_xml`
- `--enable-auto-tool-choice`

The library sends tools as OpenAI-compatible payloads and consumes `tool_calls` from the response.

## Observability and Events

`AgentKernel` emits events for each turn:

- `KernelStartEvent`, `ModelRequestEvent`, `ModelResponseEvent`
- `ToolCallEvent`, `ToolResultEvent`, `TurnCompleteEvent`, `KernelEndEvent`

Attach an observer to capture telemetry:

```python
from structured_agents.events import CompositeObserver, NullObserver

observer = CompositeObserver([NullObserver()])
kernel = AgentKernel(client=client, adapter=adapter, tools=tools, observer=observer)
```

## Error Handling

- **API failures** raise `KernelError` with phase context.
- **Tool failures** are returned as `ToolResult` with `is_error=True` and still appear in history.
- Validate tool schemas carefully; invalid schemas will lead to model-side failures or tool call errors.

## Best Practices

- Keep tool schemas minimal and explicit.
- Always pass tool schemas that match your tool implementations.
- Use structured outputs only when you need strict schema guarantees.
- Start with native tool calling; enable constraints incrementally.
- Log `ToolResult` failures and surface them in user-facing responses.

## Troubleshooting

**No tool calls returned**
- Ensure your model supports tool calling and the server is configured with a tool parser.
- Verify tool schemas are passed to `AgentKernel.run`.

**Invalid arguments from the model**
- Tighten your JSON schema or tool descriptions.
- Use `StructuredOutputModel` with `json_schema` strategy for stronger guarantees.

**Tool execution errors**
- Ensure tool implementations handle missing or malformed arguments defensively.

## Reference Checklist

- `AgentKernel`: core loop and execution.
- `ModelAdapter`: formatting, parsing, optional constraints.
- `Tool` + `ToolSchema`: tool integration surface.
- `DecodingConstraint` + `ConstraintPipeline`: structured outputs.
- `StructuredOutputModel`: Pydantic JSON schema base class.
- `build_client`: OpenAI-compatible client factory.

## Related Docs

- `README.md`
- `ARCHITECTURE.md`
- `GRAMMAR_INTEGRATION_REPORT.md`
- `V033_GRAMMAR_REFACTORING_GUIDE.md`
- `STRUCTURAL_TAG_VLLM_ERROR.md`
