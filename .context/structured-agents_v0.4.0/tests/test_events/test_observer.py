# tests/test_events/test_observer.py
import pytest
from structured_agents.events.types import (
    Event,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from structured_agents.events.observer import Observer, NullObserver


@pytest.mark.asyncio
async def test_null_observer_emit():
    observer = NullObserver()
    event = KernelStartEvent(max_turns=10, tools_count=3, initial_messages_count=1)
    # Should not raise
    await observer.emit(event)


@pytest.mark.asyncio
async def test_observer_pattern_matching():
    received_events = []

    class TestObserver:
        async def emit(self, event: Event):
            received_events.append(event)

    observer = TestObserver()
    await observer.emit(
        KernelStartEvent(max_turns=5, tools_count=2, initial_messages_count=1)
    )
    await observer.emit(
        ToolCallEvent(turn=1, tool_name="test", call_id="c1", arguments={})
    )

    assert len(received_events) == 2
