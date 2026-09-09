# apps/api/tests/services/agents/runtime/test_cancellation.py

"""Focused tests for cooperative run cancellation helpers."""

import asyncio
from uuid import uuid4

import pytest

from services.agents.runtime.cancellation import AGENT_RUN_CANCEL_REQUEST
from services.agents.runtime.run_manager import RunTaskRegistry
from services.agents.runtime.sinks import StreamSink

pytestmark = pytest.mark.asyncio


async def test_stopping_heartbeat_preserves_cancellation_of_waiting_worker():
    from services.agents.runtime.heartbeat import stop_agent_run_heartbeat

    started, stopping, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def ticker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopping.set()
            await release.wait()

    heartbeat = asyncio.create_task(ticker())
    await started.wait()
    worker = asyncio.create_task(stop_agent_run_heartbeat(asyncio.Event(), heartbeat))
    try:
        await asyncio.wait_for(stopping.wait(), timeout=1)
        worker.cancel("run_process_shutdown")
        with pytest.raises(asyncio.CancelledError, match="run_process_shutdown"):
            await worker
    finally:
        release.set()
        await asyncio.gather(heartbeat, worker, return_exceptions=True)


async def test_run_task_registry_cancel_cleans_up_task_before_it_starts() -> None:
    registry = RunTaskRegistry()
    release = asyncio.Event()
    run_id = uuid4()
    sink = StreamSink(run_id=run_id, conversation_id=uuid4(), max_queue_size=2)
    worker = release.wait()

    task = registry.spawn(run_id, worker, sink=sink)
    assert registry.cancel(run_id) is True

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task
    await registry.drain(max_wait_seconds=1)
    assert AGENT_RUN_CANCEL_REQUEST in exc_info.value.args
    assert task.cancelled()
    assert registry.cancel(run_id) is False
    assert worker.cr_frame is None
    assert await asyncio.wait_for(sink.next_frame(), timeout=1) is None


@pytest.mark.parametrize(
    "status,reason",
    [
        ("cancelled", "agent_run_cancel_requested"),
        ("failed", "run_lease_lost"),
        ("running", "run_lease_lost"),
    ],
)
async def test_heartbeat_stops_revoked_execution(monkeypatch, status, reason):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from services.agent_runs.execution_state import ExecutionState
    from services.agents.runtime.heartbeat import heartbeat_agent_run_lease
    from tests.support.execution import build_execution_control

    control = build_execution_control()
    owner = "replacement" if status == "running" else control.owner_instance_id
    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.renew_agent_run_lease_once",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "services.agents.runtime.execution_control.read_execution_states",
        AsyncMock(
            return_value={
                control.run_id: ExecutionState(
                    status, owner, datetime.now(UTC) + timedelta(seconds=90)
                ),
            }
        ),
    )
    target = asyncio.create_task(asyncio.Event().wait())
    await heartbeat_agent_run_lease(
        execution_control=control,
        stop=asyncio.Event(),
        cancel_target=target,
        renew_immediately=True,
    )
    with pytest.raises(asyncio.CancelledError) as caught:
        await target
    assert caught.value.args == (reason,)


async def test_heartbeat_outage_stops_at_confirmed_lease_deadline(monkeypatch):
    from unittest.mock import AsyncMock

    from services.agents.runtime.heartbeat import heartbeat_agent_run_lease
    from tests.support.execution import build_execution_control

    control = build_execution_control()
    control.lease_deadline = asyncio.get_running_loop().time() - 1
    renewal = AsyncMock(side_effect=RuntimeError("Database unavailable"))
    monkeypatch.setattr("services.agents.runtime.heartbeat.renew_agent_run_lease_once", renewal)
    target = asyncio.create_task(asyncio.Event().wait())
    await heartbeat_agent_run_lease(
        execution_control=control,
        stop=asyncio.Event(),
        cancel_target=target,
        renew_immediately=True,
    )
    with pytest.raises(asyncio.CancelledError) as caught:
        await target
    assert caught.value.args == ("run_lease_lost",)
    assert renewal.call_count == 1


@pytest.mark.parametrize("status", ["completed", "awaiting_approval"])
async def test_heartbeat_does_not_interrupt_own_committed_finalisation(monkeypatch, status):
    from unittest.mock import AsyncMock

    from services.agent_runs.execution_state import ExecutionState
    from services.agents.runtime.execution_control import ExecutionPhase
    from services.agents.runtime.heartbeat import heartbeat_agent_run_lease
    from tests.support.execution import build_execution_control

    control = build_execution_control()
    control.phase = ExecutionPhase.FINALISING
    control.deadline = asyncio.get_running_loop().time() - 1
    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.renew_agent_run_lease_once",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "services.agents.runtime.execution_control.read_execution_states",
        AsyncMock(
            return_value={
                control.run_id: ExecutionState(status, control.owner_instance_id, None),
            }
        ),
    )
    target = asyncio.create_task(asyncio.Event().wait())
    try:
        await heartbeat_agent_run_lease(
            execution_control=control,
            stop=asyncio.Event(),
            cancel_target=target,
            renew_immediately=True,
        )
        assert not target.cancelling()
        assert control.reason is None
    finally:
        target.cancel()
        await asyncio.gather(target, return_exceptions=True)


@pytest.mark.parametrize("repeat_cancel", [False, True])
async def test_finalisation_first_wait_is_bounded_and_joins_task(repeat_cancel):
    from services.agents.runtime.execute.bounded_finalisation import bounded_finalisation

    entered = asyncio.Event()
    exited = asyncio.Event()

    async def blocked_checkout():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            exited.set()

    task = asyncio.create_task(bounded_finalisation(blocked_checkout(), max_wait=0.02))
    try:
        await entered.wait()
        if repeat_cancel:
            task.cancel("shutdown")
            await asyncio.sleep(0)
            task.cancel("shutdown again")
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.5)
        else:
            assert not await asyncio.wait_for(task, timeout=0.5)
        assert exited.is_set()
        assert not [
            task for task in asyncio.all_tasks() if task.get_name() == "agent-run-finalisation"
        ]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_finalisation_database_error_propagates_without_live_task():
    from services.agents.runtime.execute.bounded_finalisation import bounded_finalisation

    async def failed_checkout():
        raise RuntimeError("checkout failed")

    with pytest.raises(RuntimeError, match="checkout failed"):
        await bounded_finalisation(failed_checkout(), max_wait=0.02)
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "agent-run-finalisation"]


async def test_resistant_cleanup_retains_its_owned_resources_under_supervision():
    from services.agents.runtime.execute.bounded_finalisation import bounded_finalisation

    release = asyncio.Event()
    closed = asyncio.Event()
    owned_task = None

    async def isolated_operation():
        nonlocal owned_task
        owned_task = asyncio.current_task()
        try:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
        finally:
            closed.set()

    try:
        assert not await bounded_finalisation(isolated_operation(), max_wait=0.01)
        assert owned_task is not None and not owned_task.done()
        assert not closed.is_set()
    finally:
        release.set()
        if owned_task is not None:
            await asyncio.wait_for(owned_task, timeout=1)
    assert closed.is_set()
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "agent-run-finalisation"]
