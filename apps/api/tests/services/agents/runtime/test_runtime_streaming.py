# apps/api/tests/services/agents/runtime/test_runtime_streaming.py

"""Tests for detached runtime streaming helpers."""

import asyncio
from uuid import uuid4

import pytest

from core.settings import settings
from services.agents.runtime import run_manager as run_manager_module
from services.agents.runtime.run_manager import RunTaskRegistry
from services.agents.runtime.sinks import CollectingSink, StreamSink
from services.agents.runtime.stream_protocol import DoneEvent, RunStatusEvent
from services.conversations.create_turn_stream import SSE_KEEPALIVE_FRAME, _drain_sse_sink
from tests.support.execution import build_execution_control

pytestmark = pytest.mark.asyncio


async def test_run_task_registry_queues_above_limit_then_admits_next() -> None:
    registry = RunTaskRegistry(max_concurrent_turns=2)
    release = asyncio.Event()
    started: list[int] = []
    sinks = [
        StreamSink(run_id=uuid4(), conversation_id=uuid4(), max_queue_size=10) for _ in range(3)
    ]

    async def worker(index: int) -> None:
        started.append(index)
        await release.wait()

    tasks = [
        registry.spawn(sink.run_id, worker(index), sink=sink) for index, sink in enumerate(sinks)
    ]
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert started == [0, 1]
    queued_frame = await asyncio.wait_for(sinks[2].next_frame(), timeout=1)
    assert queued_frame is not None
    assert '"status":"queued"' in queued_frame

    release.set()
    await asyncio.gather(*tasks)
    assert started == [0, 1, 2]


async def test_run_task_registry_cancels_queued_turn_without_consuming_slot() -> None:
    registry = RunTaskRegistry(max_concurrent_turns=1)
    release = asyncio.Event()
    queued_started = False
    queued_sink = StreamSink(run_id=uuid4(), conversation_id=uuid4(), max_queue_size=10)

    async def queued_worker() -> None:
        nonlocal queued_started
        queued_started = True

    first_id = uuid4()
    first = registry.spawn(first_id, release.wait())
    await asyncio.sleep(0)
    queued_id = queued_sink.run_id
    queued = registry.spawn(queued_id, queued_worker(), sink=queued_sink)
    await asyncio.sleep(0)

    queued_frame = await asyncio.wait_for(queued_sink.next_frame(), timeout=1)
    assert queued_frame is not None
    assert '"status":"queued"' in queued_frame

    assert registry.cancel(queued_id)
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert queued_started is False
    assert await asyncio.wait_for(queued_sink.next_frame(), timeout=1) is None

    release.set()
    await first
    replacement_started = asyncio.Event()

    async def replacement_worker() -> None:
        replacement_started.set()

    replacement = registry.spawn(uuid4(), replacement_worker())
    await replacement
    assert replacement_started.is_set()


async def test_run_task_registry_renews_lease_while_turn_is_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = RunTaskRegistry(max_concurrent_turns=1)
    release = asyncio.Event()
    heartbeat_started = asyncio.Event()
    heartbeat_stopped = asyncio.Event()
    workspace_id = uuid4()
    user_id = uuid4()

    async def fake_heartbeat(**kwargs) -> None:
        assert kwargs["execution_control"].workspace_id == workspace_id
        assert kwargs["execution_control"].user_id == user_id
        assert kwargs["renew_immediately"] is True
        heartbeat_started.set()
        try:
            await kwargs["stop"].wait()
        finally:
            heartbeat_stopped.set()

    monkeypatch.setattr(run_manager_module, "heartbeat_agent_run_lease", fake_heartbeat)

    first = registry.spawn(uuid4(), release.wait())
    await asyncio.sleep(0)
    queued_sink = StreamSink(run_id=uuid4(), conversation_id=uuid4(), max_queue_size=10)
    queued = registry.spawn(
        queued_sink.run_id,
        asyncio.sleep(0),
        sink=queued_sink,
        execution_control=build_execution_control(
            run_id=queued_sink.run_id, workspace_id=workspace_id, user_id=user_id
        ),
    )

    await asyncio.wait_for(heartbeat_started.wait(), timeout=1)
    release.set()
    await asyncio.gather(first, queued)

    assert heartbeat_stopped.is_set()


async def test_run_task_registry_bounds_forty_turns_below_ten_connection_slots() -> None:
    registry = RunTaskRegistry(max_concurrent_turns=6)
    connection_slots = asyncio.Semaphore(10)
    all_admitted = asyncio.Event()
    release_model_wait = asyncio.Event()
    admitted = 0
    connections_in_use = 0
    peak_connections_in_use = 0
    sinks = [CollectingSink(run_id=uuid4(), conversation_id=uuid4()) for _ in range(40)]

    async def tool_turn() -> None:
        nonlocal admitted, connections_in_use, peak_connections_in_use
        async with connection_slots:
            connections_in_use += 1
            peak_connections_in_use = max(peak_connections_in_use, connections_in_use)
            await asyncio.sleep(0)
            connections_in_use -= 1
        admitted += 1
        if admitted == 6:
            all_admitted.set()
        await release_model_wait.wait()

    tasks = [registry.spawn(sink.run_id, tool_turn(), sink=sink) for sink in sinks]
    await asyncio.wait_for(all_admitted.wait(), timeout=1)
    await asyncio.sleep(0)

    assert admitted == 6
    assert connections_in_use == 0
    assert peak_connections_in_use <= 6
    assert (
        sum(event.data.get("status") == "queued" for sink in sinks for event in sink.events) == 34
    )

    release_model_wait.set()
    await asyncio.gather(*tasks)
    assert admitted == 40


async def test_stream_sink_detaches_when_bounded_queue_is_full() -> None:
    sink = StreamSink(run_id=uuid4(), conversation_id=uuid4(), max_queue_size=1)

    await sink.emit(RunStatusEvent(status="pending"))
    await sink.emit(RunStatusEvent(status="running"))

    assert sink.detached
    assert await sink.next_frame() is None


async def test_stream_drain_emits_keepalive_without_dropping_later_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_RUN_STREAM_KEEPALIVE_SECONDS", 0.01)
    sink = StreamSink(run_id=uuid4(), conversation_id=uuid4())
    stream = _drain_sse_sink(sink)

    keepalive = await asyncio.wait_for(anext(stream), timeout=1)
    assert keepalive == SSE_KEEPALIVE_FRAME

    await sink.emit(DoneEvent(status="completed"))
    frame = await asyncio.wait_for(anext(stream), timeout=1)
    assert "event: done" in frame

    await sink.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(stream), timeout=1)
