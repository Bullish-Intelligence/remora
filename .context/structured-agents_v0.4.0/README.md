# structured-agents

Structured tool orchestration with native tool calling and optional structured outputs.
`structured-agents` provides a focused, composable agent loop that integrates model calls, tool execution, and observable events without taking over workspace or multi-agent coordination.

## What This Library Is

- A minimal, reusable agent kernel for tool-calling workflows.
- A model adapter layer that formats requests and parses tool calls.
- A tool protocol for integrating Python tools or Grail `.pym` tools.
- An optional structured output pipeline for JSON schema constraints.
- An event system for diagnostics and observability.

## What This Library Is Not

- A multi-agent orchestrator.
- A workspace or filesystem manager.
- A code discovery or parsing engine.

## Installation

```bash
pip install structured-agents
```

Python 3.13+ is required. Optional extras:

```bash
pip install "structured-agents[grammar]"   # xgrammar structured outputs
pip install "structured-agents[vllm]"      # vLLM client/server compatibility
```

`structured-agents` expects an OpenAI-compatible API (vLLM, etc.). Grammar-constrained decoding is optional and relies on XGrammar when enabled. Grail is required if you execute `.pym` tools.

## Quick Start

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

## Optional Structured Outputs

Native tool calling is the default. If you want JSON schema-constrained outputs, attach a `ConstraintPipeline` with a `DecodingConstraint` and a `StructuredOutputModel`. Constraints are only attached when tool schemas are provided to the kernel.

```python
from structured_agents import DecodingConstraint, StructuredOutputModel
from structured_agents.grammar.pipeline import ConstraintPipeline


class StatusOutput(StructuredOutputModel):
    status: str
    detail: str


constraint = DecodingConstraint(strategy="json_schema", schema_model=StatusOutput)
adapter = ModelAdapter(
    name="qwen",
    response_parser=QwenResponseParser(),
    constraint_pipeline=ConstraintPipeline(constraint),
)
```

When a constraint pipeline is present, the kernel attaches `structured_outputs` to the OpenAI-compatible request via `extra_body`.

## Kernel Configuration

`AgentKernel` exposes runtime settings such as:

- `max_tokens`
- `temperature`
- `max_concurrency`
- `max_history_messages`

These are passed directly to the OpenAI-compatible API where applicable.

## Observability

The kernel emits events during execution. Observers can stream logs, drive TUIs, or capture telemetry.

```python
from structured_agents.events import CompositeObserver, NullObserver

observer = CompositeObserver([NullObserver()])
```

## Documentation

- `HOW_TO_USE_STRUCTURED_AGENTS.md`
- `ARCHITECTURE.md`
- `GRAMMAR_INTEGRATION_REPORT.md`
- `V033_GRAMMAR_REFACTORING_GUIDE.md`
- `STRUCTURAL_TAG_VLLM_ERROR.md`

## API Overview

- `AgentKernel`: core agent loop and lifecycle.
- `ModelAdapter`: model-specific formatting and response parsing.
- `Tool`: protocol for tool schema + execution.
- `DecodingConstraint`: optional grammar configuration.
- `ConstraintPipeline`: builds structured output payloads.
- `StructuredOutputModel`: Pydantic base class for JSON schema outputs.
- `Observer`: event hooks for external integrations.
- `build_client`: OpenAI-compatible client factory.

## Project Status

The library is actively evolving. The core agent loop and tool calling APIs are stable; optional structured output features may evolve as backend support improves.

## License

MIT
