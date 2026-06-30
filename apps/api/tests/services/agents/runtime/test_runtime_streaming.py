# apps/api/tests/services/agents/runtime/test_runtime_streaming.py

"""Tests for detached runtime streaming helpers."""

import asyncio
from uuid import uuid4

import pytest

from core.settings import settings
from services.agents.runtime.events import EVENT_DONE, EVENT_RUN_STATUS
from services.agents.runtime.run_manager import RunTaskRegistry
from services.agents.runtime.sinks import StreamSink
from services.conversations.create_turn_stream import SSE_KEEPALIVE_FRAME, _drain_sse_sink

pytestmark = pytest.mark.asyncio


async def test_run_task_registry_holds_and_discards_task() -> None:
    registry = RunTaskRegistry()
    run_id = uuid4()
    release = asyncio.Event()

    async def worker() -> None:
        await release.wait()

    task = registry.spawn(run_id, worker())
    assert registry.is_running(run_id)

    release.set()
    await task
    await asyncio.sleep(0)

    assert not registry.is_running(run_id)


async def test_run_task_registry_drain_waits_for_in_flight_task() -> None:
    registry = RunTaskRegistry()
    run_id = uuid4()
    completed = False

    async def worker() -> None:
        nonlocal completed
        await asyncio.sleep(0)
        completed = True

    registry.spawn(run_id, worker())
    await registry.drain(max_wait_seconds=1)

    assert completed
    assert not registry.is_running(run_id)


async def test_stream_drain_detaches_sink_when_consumer_closes() -> None:
    sink = StreamSink(run_id=uuid4(), conversation_id=uuid4())
    await sink.emit(EVENT_RUN_STATUS, {"status": "pending"})

    stream = _drain_sse_sink(sink)
    frame = await anext(stream)
    await stream.aclose()

    assert "event: run.status" in frame
    assert sink.detached

    await sink.emit(EVENT_DONE, {"status": "completed"})
    await sink.close()


async def test_stream_drain_emits_keepalive_without_dropping_later_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_RUN_STREAM_KEEPALIVE_SECONDS", 0.01)
    sink = StreamSink(run_id=uuid4(), conversation_id=uuid4())
    stream = _drain_sse_sink(sink)

    keepalive = await asyncio.wait_for(anext(stream), timeout=1)
    assert keepalive == SSE_KEEPALIVE_FRAME

    await sink.emit(EVENT_DONE, {"status": "completed"})
    frame = await asyncio.wait_for(anext(stream), timeout=1)
    assert "event: done" in frame

    await sink.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=1)
