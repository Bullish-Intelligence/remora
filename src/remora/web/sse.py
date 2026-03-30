"""Server-sent event streaming endpoints."""

from __future__ import annotations

import asyncio
import json

from starlette.requests import Request
from starlette.responses import StreamingResponse

from remora.web.deps import _deps_from_request


async def _wait_for_shutdown(event: asyncio.Event) -> None:
    await event.wait()


async def _wait_for_disconnect(request: Request) -> None:
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.25)


async def sse_stream(request: Request) -> StreamingResponse:
    deps = _deps_from_request(request)
    once = request.query_params.get("once", "").lower() in {"1", "true", "yes"}
    replay_raw = request.query_params.get("replay", "0")
    last_event_id = request.headers.get("Last-Event-ID")
    try:
        replay_limit = max(0, min(500, int(replay_raw)))
    except ValueError:
        replay_limit = 0

    async def event_generator():
        yield ": connected\n\n"
        if last_event_id:
            rows = await deps.event_store.get_events_after(last_event_id)
            for row in rows:
                event_name = row.get("event_type", "Event")
                event_id = row.get("id", "")
                replay_payload = {
                    "event_type": event_name,
                    "timestamp": row.get("timestamp"),
                    "correlation_id": row.get("correlation_id"),
                    "tags": row.get("tags", []),
                    "payload": row.get("payload", {}),
                }
                payload_text = json.dumps(replay_payload, separators=(",", ":"))
                yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
        elif replay_limit > 0:
            rows = await deps.event_store.get_events(limit=replay_limit)
            for row in reversed(rows):
                event_name = row.get("event_type", "Event")
                event_id = row.get("id", "")
                replay_payload = {
                    "event_type": event_name,
                    "timestamp": row.get("timestamp"),
                    "correlation_id": row.get("correlation_id"),
                    "tags": row.get("tags", []),
                    "payload": row.get("payload", {}),
                }
                payload_text = json.dumps(replay_payload, separators=(",", ":"))
                yield f"id: {event_id}\nevent: {event_name}\ndata: {payload_text}\n\n"
        if once:
            return
        async with deps.event_bus.stream() as stream:
            stream_iterator = stream.__aiter__()
            disconnect_task = asyncio.create_task(
                _wait_for_disconnect(request), name="sse-disconnect"
            )
            shutdown_task = asyncio.create_task(
                _wait_for_shutdown(deps.shutdown_event), name="sse-shutdown"
            )
            sentinel_tasks = {disconnect_task, shutdown_task}
            try:
                while True:
                    stream_task = asyncio.create_task(stream_iterator.__anext__())
                    done, _ = await asyncio.wait(
                        sentinel_tasks | {stream_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if stream_task not in done:
                        stream_task.cancel()
                        try:
                            await stream_task
                        except (asyncio.CancelledError, StopAsyncIteration):
                            pass
                        break
                    try:
                        event = stream_task.result()
                    except StopAsyncIteration:
                        break
                    payload = json.dumps(event.to_envelope(), separators=(",", ":"))
                    sse_id = event.event_id if event.event_id is not None else event.timestamp
                    yield f"id: {sse_id}\nevent: {event.event_type}\ndata: {payload}\n\n"
            finally:
                for task in sentinel_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*sentinel_tasks, return_exceptions=True)
        if deps.shutdown_event.is_set():
            yield ": server-shutdown\n\n"

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)


__all__ = ["sse_stream"]
