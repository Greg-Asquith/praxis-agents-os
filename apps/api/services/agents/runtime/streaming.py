# apps/api/services/agents/runtime/streaming.py

"""Shared SSE stream-drain helpers for live runtime sinks."""

import asyncio
from collections.abc import AsyncIterator

from core.settings import settings
from services.agents.runtime.sinks import StreamSink

SSE_KEEPALIVE_FRAME = ": keepalive\n\n"


async def drain_sse_sink(sink: StreamSink) -> AsyncIterator[str]:
    """Yield SSE frames from a sink until it closes."""
    pending_frame: asyncio.Task[str | None] | None = None
    try:
        while True:
            if pending_frame is None:
                pending_frame = asyncio.create_task(sink.next_frame())

            done, _pending = await asyncio.wait(
                {pending_frame},
                timeout=settings.AGENT_RUN_STREAM_KEEPALIVE_SECONDS,
            )
            if not done:
                yield SSE_KEEPALIVE_FRAME
                continue

            frame = pending_frame.result()
            pending_frame = None
            if frame is None:
                break
            yield frame
    except asyncio.CancelledError:
        raise
    finally:
        if pending_frame is not None and not pending_frame.done():
            pending_frame.cancel()
        sink.detach()
