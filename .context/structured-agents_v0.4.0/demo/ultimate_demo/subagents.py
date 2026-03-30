from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from structured_agents.client import build_client
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.parsing import DefaultResponseParser
from structured_agents.tools.protocol import Tool
from structured_agents.types import Message, ToolCall, ToolResult, ToolSchema

from demo.ultimate_demo.config import API_KEY, BASE_URL, GRAMMAR_CONFIG, MODEL_NAME
from demo.ultimate_demo.state import DemoState, RiskItem


@dataclass(frozen=True, slots=True)
class SubagentSpec:
    name: str
    description: str
    system_prompt: str


@dataclass
class SubagentMemory:
    plan_steps: list[str] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    tool_log: list[str] = field(default_factory=list)


@dataclass
class PlanStepsTool(Tool):
    memory: SubagentMemory

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="capture_plan",
            description="Capture an ordered plan as bullet steps",
            parameters={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["steps"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        steps = arguments.get("steps", [])
        if isinstance(steps, list):
            self.memory.plan_steps.extend([str(step) for step in steps])
        self.memory.tool_log.append("capture_plan")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output="Plan captured",
            is_error=False,
        )


@dataclass
class RiskCaptureTool(Tool):
    memory: SubagentMemory

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="capture_risk",
            description="Capture a risk and mitigation",
            parameters={
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "mitigation": {"type": "string"},
                },
                "required": ["description", "mitigation"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        description = str(arguments.get("description", ""))
        mitigation = str(arguments.get("mitigation", ""))
        self.memory.risks.append(
            RiskItem(description=description, mitigation=mitigation)
        )
        self.memory.tool_log.append("capture_risk")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output="Risk captured",
            is_error=False,
        )


@dataclass
class InsightCaptureTool(Tool):
    memory: SubagentMemory

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="capture_insight",
            description="Capture a concise subagent insight",
            parameters={
                "type": "object",
                "properties": {"insight": {"type": "string"}},
                "required": ["insight"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        insight = str(arguments.get("insight", ""))
        if insight:
            self.memory.insights.append(insight)
        self.memory.tool_log.append("capture_insight")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=insight,
            is_error=False,
        )


@dataclass
class SubagentTool(Tool):
    state: DemoState
    spec: SubagentSpec
    observer: Observer | None = None

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.spec.name,
            description=self.spec.description,
            parameters={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Task for the subagent to complete",
                    }
                },
                "required": ["task"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        task = str(arguments.get("task", ""))
        memory = SubagentMemory()
        tools = [
            PlanStepsTool(memory),
            RiskCaptureTool(memory),
            InsightCaptureTool(memory),
        ]
        kernel = _build_subagent_kernel(tools, observer=self.observer)
        messages = [
            Message(role="system", content=self.spec.system_prompt),
            Message(role="user", content=task),
        ]
        tool_schemas = [tool.schema for tool in tools]
        try:
            result = await kernel.run(messages, tool_schemas, max_turns=3)
        finally:
            await kernel.close()

        if memory.plan_steps:
            self.state.updates.append(
                f"{self.spec.name} plan: " + " | ".join(memory.plan_steps)
            )
        if memory.insights:
            self.state.updates.extend(
                [f"{self.spec.name} insight: {insight}" for insight in memory.insights]
            )
        if memory.risks:
            self.state.risks.extend(memory.risks)

        self.state.tool_log.append(self.spec.name)
        summary = _summarize_subagent(result, memory)
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=summary,
            is_error=False,
        )


SUBAGENT_SPECS = [
    SubagentSpec(
        name="task_planner",
        description="Break down work into clear steps",
        system_prompt=(
            "You are a project planning subagent. Use capture_plan to record steps, "
            "capture_insight for key notes, and capture_risk if you spot delivery risk."
        ),
    ),
    SubagentSpec(
        name="risk_analyst",
        description="Identify delivery risks and mitigations",
        system_prompt=(
            "You are a risk analyst. Use capture_risk for each risk, and capture_insight "
            "for mitigations or warnings."
        ),
    ),
]


def build_subagent_tools(
    state: DemoState, observer: Observer | None = None
) -> list[Tool]:
    return [
        SubagentTool(state=state, spec=spec, observer=observer)
        for spec in SUBAGENT_SPECS
    ]


def _build_subagent_kernel(tools: list[Tool], observer: Observer | None) -> AgentKernel:
    """Build subagent kernel with v0.4 API."""
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
        tools=tools,
        observer=observer or NullObserver(),
    )


def _summarize_subagent(result: Any, memory: SubagentMemory) -> str:
    summary_lines = ["Subagent summary:"]
    if memory.plan_steps:
        summary_lines.append("Plan steps: " + ", ".join(memory.plan_steps))
    if memory.risks:
        summary_lines.append(f"Risks captured: {len(memory.risks)}")
    if memory.insights:
        summary_lines.append("Insights: " + "; ".join(memory.insights))
    if result.final_message.content:
        summary_lines.append(f"Final message: {result.final_message.content}")
    return "\n".join(summary_lines)
