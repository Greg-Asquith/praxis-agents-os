# apps/api/tests/services/agents/runtime/test_cancellation.py

"""Focused tests for cooperative run cancellation helpers."""

import asyncio
from uuid import uuid4

import pytest

from services.agents.runtime.cancellation import AGENT_RUN_CANCEL_REQUEST
from services.agents.runtime.run_manager import RunTaskRegistry
from services.agents.runtime.sinks import StreamSink

pytestmark = pytest.mark.asyncio


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
