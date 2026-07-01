# apps/api/tests/services/conversations/test_create_conversation_stream.py

"""Tests for conversation create-stream helpers."""

import asyncio
from uuid import uuid4

import pytest

from services.agents.runtime.events import EVENT_DONE
from services.agents.runtime.sinks import StreamSink
from services.conversations.create_conversation_stream import _CloseAfterTitleTaskSink

pytestmark = pytest.mark.asyncio


async def test_title_task_sink_forwards_done_before_waiting_to_close() -> None:
    release_title = asyncio.Event()

    async def slow_title_task() -> None:
        await release_title.wait()

    title_task = asyncio.create_task(slow_title_task())
    stream_sink = StreamSink(run_id=uuid4(), conversation_id=uuid4())
    title_update_sink = _CloseAfterTitleTaskSink(
        stream_sink,
        title_task,
        wait_timeout_seconds=0.01,
    )

    await asyncio.wait_for(
        title_update_sink.emit(EVENT_DONE, {"status": "completed"}),
        timeout=1,
    )

    assert not title_task.done()
    assert not title_task.cancelled()
    frame = await asyncio.wait_for(stream_sink.next_frame(), timeout=1)
    assert "event: done" in frame

    await title_update_sink.close()
    release_title.set()
    await title_task
