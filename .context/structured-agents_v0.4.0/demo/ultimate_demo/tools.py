from dataclasses import dataclass
from typing import Any, cast

from structured_agents.tools.protocol import Tool
from structured_agents.types import ToolCall, ToolResult, ToolSchema

from demo.ultimate_demo.state import DemoState, RiskItem, Status, TaskItem


@dataclass
class AddTaskTool(Tool):
    state: DemoState

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="add_task",
            description="Add a new project task",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "status": {"type": "string"},
                    "owner": {"type": "string"},
                },
                "required": ["title", "status"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        title = str(arguments.get("title", ""))
        status = _normalize_status(arguments.get("status"))
        owner = arguments.get("owner")
        task = TaskItem(title=title, status=status, owner=owner)
        self.state.tasks.append(task)

        self.state.tool_log.append("add_task")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=f"Added task: {title}",
            is_error=False,
        )


@dataclass
class UpdateTaskStatusTool(Tool):
    state: DemoState

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="update_task_status",
            description="Update status for an existing task",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["title", "status"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        title = str(arguments.get("title", ""))
        status = _normalize_status(arguments.get("status"))
        task = _find_task(self.state, title)
        if task is None:
            return ToolResult(
                call_id=context.id if context else "",
                name=self.schema.name,
                output=f"Task not found: {title}",
                is_error=True,
            )
        task.status = status  # type: ignore[assignment]
        self.state.tool_log.append("update_task_status")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=f"Updated {title} to {status}",
            is_error=False,
        )


@dataclass
class RecordRiskTool(Tool):
    state: DemoState

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="record_risk",
            description="Record a delivery risk and mitigation",
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
        self.state.risks.append(
            RiskItem(description=description, mitigation=mitigation)
        )
        self.state.tool_log.append("record_risk")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output="Risk recorded",
            is_error=False,
        )


@dataclass
class LogUpdateTool(Tool):
    state: DemoState

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="log_update",
            description="Log a stakeholder update",
            parameters={
                "type": "object",
                "properties": {"update": {"type": "string"}},
                "required": ["update"],
            },
        )

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        update = str(arguments.get("update", ""))
        self.state.updates.append(update)
        self.state.tool_log.append("log_update")
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=update,
            is_error=False,
        )


def build_demo_tools(state: DemoState) -> list[Tool]:
    return [
        AddTaskTool(state),
        UpdateTaskStatusTool(state),
        RecordRiskTool(state),
        LogUpdateTool(state),
    ]


def _find_task(state: DemoState, title: str) -> TaskItem | None:
    for task in state.tasks:
        if task.title == title:
            return task
    return None


def _normalize_status(value: Any | None) -> Status:
    candidate = str(value) if value is not None else "open"
    if candidate in {"open", "in_progress", "blocked", "done"}:
        return cast(Status, candidate)
    return "open"
