from dataclasses import dataclass, field
from typing import Literal

Status = Literal["open", "in_progress", "blocked", "done"]


@dataclass
class TaskItem:
    title: str
    status: Status
    owner: str | None = None


@dataclass
class RiskItem:
    description: str
    mitigation: str


@dataclass
class DemoState:
    inbox: list[str] = field(default_factory=list)
    outbox: list[str] = field(default_factory=list)
    tasks: list[TaskItem] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    tool_log: list[str] = field(default_factory=list)

    @classmethod
    def initial(cls) -> "DemoState":
        return cls()

    def summary(self) -> str:
        task_lines = [
            f"- {task.title} ({task.status})"
            + (f" owner={task.owner}" if task.owner else "")
            for task in self.tasks
        ]
        risk_lines = [
            f"- {risk.description} -> {risk.mitigation}" for risk in self.risks
        ]
        update_lines = [f"- {update}" for update in self.updates]
        tool_log = ", ".join(self.tool_log) if self.tool_log else "(none)"

        summary_lines = ["State Summary:", "Tasks:"]
        summary_lines.extend(task_lines or ["- none"])
        summary_lines.append("Risks:")
        summary_lines.extend(risk_lines or ["- none"])
        summary_lines.append("Updates:")
        summary_lines.extend(update_lines or ["- none"])
        summary_lines.append(f"Tool log: {tool_log}")
        return "\n".join(summary_lines)
