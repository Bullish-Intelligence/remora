from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, Protocol

from structured_agents.events.observer import Observer
from structured_agents.types import RunResult

from demo.ultimate_demo.coordinator import build_demo_coordinator
from demo.ultimate_demo.observer import DemoObserver
from demo.ultimate_demo.state import DemoState


class AgentRunner(Protocol):
    async def run(self, user_input: str, **kwargs) -> RunResult: ...


@dataclass
class DemoRunner:
    state: DemoState
    coordinator: AgentRunner
    tool_names: list[str]
    subagent_names: list[str]

    async def run(self, inbox: Iterable[str]) -> DemoState:
        self.state.inbox = list(inbox)
        self.state.outbox = []

        for message in self.state.inbox:
            result = await self.coordinator.run(message)
            self.state.outbox.append(result.final_message.content or "")

        return self.state

    def render_summary(self) -> str:
        tool_summary = ", ".join(self.tool_names)
        subagent_summary = ", ".join(self.subagent_names)
        return "\n".join(
            [
                "=== Ultimate Demo Summary ===",
                f"Tools: {tool_summary}",
                f"Subagents: {subagent_summary}",
                self.state.summary(),
            ]
        )


def build_demo_runner(observer: Observer | None = None) -> DemoRunner:
    coordinator = build_demo_coordinator(observer=observer)
    tool_names = [tool.schema.name for tool in coordinator.tools]
    subagent_names = [tool.schema.name for tool in coordinator.subagent_tools]
    return DemoRunner(
        state=coordinator.state,
        coordinator=coordinator,
        tool_names=tool_names,
        subagent_names=subagent_names,
    )


async def run_demo() -> None:
    runner = build_demo_runner(observer=DemoObserver())
    inbox = [
        "We need to add a QA review task for sprint 12.",
        "Stakeholders want a status update on the onboarding rollout.",
        "Identify risks if our integration partner slips by two weeks.",
        "Create a short plan to recover schedule if we lose three days.",
    ]
    state = await runner.run(inbox)
    print("\n".join(["=== Inbox ===", *state.inbox]))
    print("\n".join(["=== Outbox ===", *state.outbox]))
    print(runner.render_summary())


def main() -> None:
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
