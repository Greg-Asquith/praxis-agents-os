# apps/api/tests/services/agents/runtime/test_runtime_streaming.py

"""Tests for detached runtime streaming helpers."""

import asyncio
import logging
from uuid import uuid4

import pytest

from core.settings import settings
from services.agents.runtime import heartbeat as heartbeat_module, run_manager as run_manager_module
from services.agents.runtime.run_manager import QueuedRunLease, RunTaskRegistry
from services.agents.runtime.sinks import CollectingSink, StreamSink
from services.agents.runtime.stream_protocol import DoneEvent, RunStatusEvent
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
        assert kwargs["workspace_id"] == workspace_id
        assert kwargs["user_id"] == user_id
        assert kwargs["renew_immediately"] is True
        heartbeat_started.set()
        await kwargs["stop"].wait()
        heartbeat_stopped.set()

    monkeypatch.setattr(run_manager_module, "heartbeat_agent_run_lease", fake_heartbeat)

    first = registry.spawn(uuid4(), release.wait())
    await asyncio.sleep(0)
    queued_sink = StreamSink(run_id=uuid4(), conversation_id=uuid4(), max_queue_size=10)
    queued = registry.spawn(
        queued_sink.run_id,
        asyncio.sleep(0),
        sink=queued_sink,
        queued_lease=QueuedRunLease(workspace_id=workspace_id, user_id=user_id),
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


async def test_stream_drain_detaches_sink_when_consumer_closes() -> None:
    sink = StreamSink(run_id=uuid4(), conversation_id=uuid4())
    await sink.emit(RunStatusEvent(status="pending"))

    stream = _drain_sse_sink(sink)
    frame = await anext(stream)
    await stream.aclose()

    assert "event: run.status" in frame
    assert sink.detached

    await sink.emit(DoneEvent(status="completed"))
    await sink.close()


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


async def test_heartbeat_failure_logs_error_with_pool_status(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stop = asyncio.Event()

    async def fail_renewal(**_kwargs) -> bool:
        stop.set()
        raise TimeoutError("pool checkout timed out")

    monkeypatch.setattr(settings, "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(heartbeat_module, "renew_agent_run_lease_once", fail_renewal)
    monkeypatch.setattr(heartbeat_module, "_runtime_pool_status", lambda: "Pool size: 5")

    with caplog.at_level(logging.ERROR, logger=heartbeat_module.logger.name):
        await heartbeat_module.heartbeat_agent_run_lease(
            run_id=uuid4(),
            workspace_id=uuid4(),
            user_id=uuid4(),
            owner_instance_id="test-worker",
            stop=stop,
        )

    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Failed to renew agent run lease"
    )
    assert record.levelno == logging.ERROR
    assert record.pool_status == "Pool size: 5"


async def test_heartbeat_can_renew_queued_run_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = asyncio.Event()
    renewals = 0

    async def renew_once(**_kwargs) -> bool:
        nonlocal renewals
        renewals += 1
        stop.set()
        return True

    monkeypatch.setattr(heartbeat_module, "renew_agent_run_lease_once", renew_once)

    await heartbeat_module.heartbeat_agent_run_lease(
        run_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        owner_instance_id="test-worker",
        stop=stop,
        renew_immediately=True,
    )

    assert renewals == 1
