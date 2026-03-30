from __future__ import annotations

import asyncio

import pytest

from remora.core.events import AgentStartEvent, EventBus


@pytest.mark.asyncio
async def test_stream_drops_events_when_buffer_is_full(caplog) -> None:
    bus = EventBus()

    async with bus.stream(max_buffer=1) as events:
        await bus.emit(AgentStartEvent(agent_id="first"))
        await bus.emit(AgentStartEvent(agent_id="second"))

        received = await asyncio.wait_for(anext(events), timeout=1.0)
        assert received.agent_id == "first"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(anext(events), timeout=0.05)

    assert "SSE stream buffer full, dropping event agent_start" in caplog.text
