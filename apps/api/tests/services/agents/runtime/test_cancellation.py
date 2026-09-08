# apps/api/tests/services/agents/runtime/test_cancellation.py

"""Focused tests for cooperative run cancellation helpers."""

import asyncio
from contextlib import suppress
from uuid import uuid4

import pytest

from services.agent_runs.domain import RUN_STATUS_CANCELLED
from services.agents.runtime.cancellation import AGENT_RUN_CANCEL_REQUEST
from services.agents.runtime.heartbeat import cancel_target_if_run_cancelled
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


async def test_heartbeat_cancel_detection_cancels_live_target(monkeypatch: pytest.MonkeyPatch):
    run_id = uuid4()
    target = asyncio.create_task(asyncio.Event().wait())

    async def fake_status(*, run_id, **_kwargs):
        return RUN_STATUS_CANCELLED

    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.read_agent_run_status_once",
        fake_status,
    )

    delivered = await cancel_target_if_run_cancelled(
        run_id=run_id,
        workspace_id=uuid4(),
        user_id=uuid4(),
        owner_instance_id="test-worker",
        cancel_target=target,
    )

    assert delivered is True
    assert target.cancelling() > 0
    with pytest.raises(asyncio.CancelledError) as exc_info:
        await target
    assert AGENT_RUN_CANCEL_REQUEST in exc_info.value.args


async def test_heartbeat_cancel_detection_dedupes_existing_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = asyncio.create_task(asyncio.Event().wait())
    target.cancel()
    status_read = False

    async def fake_status(*, run_id, **_kwargs):
        nonlocal status_read
        status_read = True
        return RUN_STATUS_CANCELLED

    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.read_agent_run_status_once",
        fake_status,
    )

    delivered = await cancel_target_if_run_cancelled(
        run_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        owner_instance_id="test-worker",
        cancel_target=target,
    )

    assert delivered is False
    assert status_read is False
    with suppress(asyncio.CancelledError):
        await target


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
