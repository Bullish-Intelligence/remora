from structured_agents.events.observer import Observer
from structured_agents.events.types import (
    Event,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)


class DemoObserver(Observer):
    async def emit(self, event: Event) -> None:
        if isinstance(event, KernelStartEvent):
            print(f"[kernel] start max_turns={event.max_turns}")
        elif isinstance(event, KernelEndEvent):
            print(
                f"[kernel] end turns={event.turn_count} reason={event.termination_reason}"
            )
        elif isinstance(event, ModelRequestEvent):
            print(f"[model] request turn={event.turn} tools={event.tools_count}")
        elif isinstance(event, ModelResponseEvent):
            print(f"[model] response turn={event.turn} tools={event.tool_calls_count}")
        elif isinstance(event, ToolCallEvent):
            print(f"[tool] call {event.tool_name}")
        elif isinstance(event, ToolResultEvent):
            status = "error" if event.is_error else "ok"
            print(f"[tool] result {event.tool_name} status={status}")
        elif isinstance(event, TurnCompleteEvent):
            print(
                f"[turn] complete {event.turn} calls={event.tool_calls_count} errors={event.errors_count}"
            )
