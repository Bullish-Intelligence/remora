from __future__ import annotations

from dataclasses import dataclass

from structured_agents.client import build_client
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.parsing import DefaultResponseParser
from structured_agents.tools.protocol import Tool
from structured_agents.types import Message, RunResult

from demo.ultimate_demo.config import API_KEY, BASE_URL, GRAMMAR_CONFIG, MODEL_NAME
from demo.ultimate_demo.state import DemoState
from demo.ultimate_demo.subagents import build_subagent_tools
from demo.ultimate_demo.tools import build_demo_tools

SYSTEM_PROMPT = (
    "You are a project coordinator. Use tools to update state: add_task, "
    "update_task_status, record_risk, log_update. When asked for plans or risks, "
    "delegate to task_planner or risk_analyst subagents. Always call tools to "
    "record structured updates before responding."
)


@dataclass(frozen=True, slots=True)
class DemoCoordinator:
    """Coordinator wrapping a kernel with tools and state."""

    state: DemoState
    tools: list[Tool]
    subagent_tools: list[Tool]
    kernel: AgentKernel
    system_prompt: str

    async def run(self, user_input: str, **kwargs) -> RunResult:
        """Run the coordinator with a user message."""
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=user_input),
        ]
        all_tools = [*self.tools, *self.subagent_tools]
        tool_schemas = [t.schema for t in all_tools]
        max_turns = kwargs.get("max_turns", 5)
        return await self.kernel.run(messages, tool_schemas, max_turns=max_turns)

    async def close(self) -> None:
        """Close underlying resources."""
        await self.kernel.close()


def build_demo_state() -> DemoState:
    return DemoState.initial()


def build_demo_kernel(
    tools: list[Tool],
    subagent_tools: list[Tool],
    observer: Observer | None = None,
) -> AgentKernel:
    """Build kernel with v0.4 API - direct response_parser and constraint_pipeline."""
    pipeline = (
        ConstraintPipeline(GRAMMAR_CONFIG) if GRAMMAR_CONFIG is not None else None
    )

    # v0.4: Use hosted_vllm/ prefix for LiteLLM routing with grammar support
    model_name = f"hosted_vllm/{MODEL_NAME}"

    client = build_client(
        {
            "base_url": BASE_URL,
            "api_key": API_KEY,
            "model": model_name,
        }
    )
    return AgentKernel(
        client=client,
        model=model_name,
        response_parser=DefaultResponseParser(),
        constraint_pipeline=pipeline,
        tools=[*tools, *subagent_tools],
        observer=observer or NullObserver(),
    )


def build_demo_coordinator(observer: Observer | None = None) -> DemoCoordinator:
    state = build_demo_state()
    tools = build_demo_tools(state)
    subagent_tools = build_subagent_tools(state, observer=observer)
    kernel = build_demo_kernel(tools, subagent_tools, observer=observer)
    return DemoCoordinator(
        state=state,
        tools=tools,
        subagent_tools=subagent_tools,
        kernel=kernel,
        system_prompt=SYSTEM_PROMPT,
    )
