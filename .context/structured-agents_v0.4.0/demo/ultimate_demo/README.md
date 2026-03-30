# Ultimate Demo

A comprehensive demonstration of structured agents with native tool calling, subagent orchestration, and state management.

## Overview

The Ultimate Demo showcases a **project coordination agent** that manages tasks, risks, and stakeholder updates using AI-powered subagents. It demonstrates:

- **Native tool calling** via vLLM’s OpenAI-compatible API
- **Optional structured outputs** via `ConstraintPipeline` when enabled
- **Subagent delegation** for specialized tasks (planning, risk analysis)
- **State management** with structured tool calls
- **Event observation** for monitoring agent behavior

## What It Does

The demo simulates a project coordinator that processes user requests and delegates work to appropriate subagents:

1. **Main Coordinator Agent** - Handles direct state updates via tools:
   - `add_task` - Create new project tasks
   - `update_task_status` - Update existing task status
   - `record_risk` - Log delivery risks with mitigations
   - `log_update` - Record stakeholder updates

2. **Task Planner Subagent** - Delegates to this for breaking down work into clear steps

3. **Risk Analyst Subagent** - Delegates to this for identifying delivery risks and mitigations

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DemoCoordinator                          │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ DemoState    │  │ Main Agent   │  │ Subagent Tools   │  │
│  │ - tasks      │  │ (Coordinator)│  │ - task_planner   │  │
│  │ - risks      │  │              │  │ - risk_analyst   │  │
│  │ - updates    │  │              │  │                  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    AgentKernel                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ ModelClient  │  │ ModelAdapter │  │ ConstraintPipeline│ │
│  │ (vLLM)       │  │ (QwenParser) │  │ (optional)       │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Key Components

| File | Purpose |
|------|---------|
| `state.py` | `DemoState` dataclass holding tasks, risks, updates, and tool log |
| `tools.py` | State management tools (`add_task`, `update_task_status`, `record_risk`, `log_update`) |
| `subagents.py` | Subagent definitions (`task_planner`, `risk_analyst`) with memory and result capture |
| `coordinator.py` | Builds the main agent with tools, subagents, and optional constraints |
| `runner.py` | Executes the demo with sample inputs and renders results |
| `observer.py` | Event observer logging kernel, model, tool, and turn events |
| `config.py` | API endpoint, model name, and grammar configuration |

### Grammar-Constrained Decoding

The demo defaults to **native tool calling**. Grammar constraints are optional and only enabled if you set `GRAMMAR_CONFIG` to a `DecodingConstraint`.

```python
from structured_agents.grammar.config import DecodingConstraint

# Default: no constraints (native tool calling)
GRAMMAR_CONFIG = None

# Optional JSON schema constraints
# GRAMMAR_CONFIG = DecodingConstraint(
#     strategy="json_schema",
#     schema_model=YourStructuredOutputModel,
# )
```

When enabled, the `ConstraintPipeline` attaches `structured_outputs` to the OpenAI-compatible request via `extra_body`.

### Subagent Pattern

Subagents have their own:
- **Memory** - Captures plan steps, risks, and insights
- **Tools** - `capture_plan`, `capture_risk`, `capture_insight`
- **Kernel** - Isolated agent kernel with limited turns (max 3)

Results are aggregated back into the main `DemoState`.

## Running the Demo

### Prerequisites

1. **Remora Server** running at `http://remora-server:8000/v1`
   - Must serve the model: `Qwen/Qwen3-4B-Instruct-2507-FP8`
   - API key: `EMPTY`

2. **Dependencies** installed:
   ```
   pip install structured-agents
   ```

### Configuration

Edit `config.py` if using different endpoints:

```python
BASE_URL = "http://remora-server:8000/v1"
MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507-FP8"
API_KEY = "EMPTY"
```

### Run Commands

**Run the full demo:**
```bash
python -m demo.ultimate_demo.runner
```

**Or programmatically:**
```python
import asyncio
from demo.ultimate_demo import run_demo

asyncio.run(run_demo())
```

**Programmatic usage with custom observer:**
```python
from demo.ultimate_demo import build_demo_runner
from demo.ultimate_demo.observer import DemoObserver

import asyncio


async def main() -> None:
    runner = build_demo_runner(observer=DemoObserver())
    state = await runner.run([
        "We need to add a QA review task for sprint 12.",
        "Identify risks if our integration partner slips by two weeks.",
    ])
    print(state.summary())


asyncio.run(main())
```

### Sample Output

The demo processes these messages:
1. "We need to add a QA review task for sprint 12."
2. "Stakeholders want a status update on the onboarding rollout."
3. "Identify risks if our integration partner slips by two weeks."
4. "Create a short plan to recover schedule if we lose three days."

And produces structured state with:
- Tasks added to `state.tasks`
- Risks captured in `state.risks`
- Updates logged in `state.updates`
- Tool execution log in `state.tool_log`

### Event Logging

The `DemoObserver` prints events during execution:

```
[kernel] start max_turns=20
[model] request turn=1 tools=6
[tool] call add_task
[tool] result add_task status=ok
[model] response turn=1 tools=1
[turn] complete 1 calls=1 errors=0
...
[kernel] end turns=4 reason=no_tool_calls
```

## Extending the Demo

### Adding New Tools

Add tool definitions in `tools.py`:

```python
@dataclass
class MyTool(Tool):
    state: DemoState

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="my_tool",
            description="Description",
            parameters={...},
        )

    async def execute(self, arguments, context):
        # Implementation
        return ToolResult(...)
```

Then register in `build_demo_tools()`.

### Adding New Subagents

Add specs in `subagents.py`:

```python
SUBAGENT_SPECS = [
    # ... existing
    SubagentSpec(
        name="my_subagent",
        description="Description",
        system_prompt="System prompt...",
    ),
]
```

### Custom Observers

Implement the `Observer` interface:

```python
class MyObserver(Observer):
    async def emit(self, event: Event) -> None:
        # Handle events
        pass
```

Available event types:
- `KernelStartEvent`, `KernelEndEvent`
- `ModelRequestEvent`, `ModelResponseEvent`
- `ToolCallEvent`, `ToolResultEvent`
- `TurnCompleteEvent`
