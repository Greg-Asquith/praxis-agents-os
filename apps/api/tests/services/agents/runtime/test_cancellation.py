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

pytestmark = pytest.mark.asyncio


async def test_run_task_registry_cancel_delivers_to_live_task() -> None:
    registry = RunTaskRegistry()
    release = asyncio.Event()
    run_id = uuid4()

    task = registry.spawn(run_id, release.wait())
    assert registry.cancel(run_id) is True

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await task
    assert AGENT_RUN_CANCEL_REQUEST in exc_info.value.args
    assert task.cancelled()
    assert registry.cancel(run_id) is False


async def test_heartbeat_cancel_detection_cancels_live_target(monkeypatch: pytest.MonkeyPatch):
    run_id = uuid4()
    target = asyncio.create_task(asyncio.Event().wait())

    async def fake_status(*, run_id):
        return RUN_STATUS_CANCELLED

    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.read_agent_run_status_once",
        fake_status,
    )

    delivered = await cancel_target_if_run_cancelled(
        run_id=run_id,
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

    async def fake_status(*, run_id):
        nonlocal status_read
        status_read = True
        return RUN_STATUS_CANCELLED

    monkeypatch.setattr(
        "services.agents.runtime.heartbeat.read_agent_run_status_once",
        fake_status,
    )

    delivered = await cancel_target_if_run_cancelled(
        run_id=uuid4(),
        owner_instance_id="test-worker",
        cancel_target=target,
    )

    assert delivered is False
    assert status_read is False
    with suppress(asyncio.CancelledError):
        await target
