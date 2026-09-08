"""Characterises invocation permission and continuation clocks without real-time waits."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from services.agent_runs.execution_state import ExecutionState
from services.agents.runtime.execution_control import (
    ExecutionControl,
    ExecutionPhase,
    InterruptionReason,
)


def state(
    *, status: str = "running", owner: str = "owner", lease_seconds: int = 90
) -> ExecutionState:
    return ExecutionState(
        status=status,
        owner_instance_id=owner,
        lease_expires_at=datetime(2026, 9, 8, tzinfo=UTC) + timedelta(seconds=lease_seconds),
    )


@pytest.mark.parametrize("phase", [ExecutionPhase.QUEUED, ExecutionPhase.EXECUTING])
@pytest.mark.parametrize("status", ["failed", "completed", "awaiting_approval"])
def test_non_live_state_revokes_execution(phase: ExecutionPhase, status: str) -> None:
    control = ExecutionControl(
        uuid4(), uuid4(), uuid4(), "owner", deadline=100, lease_deadline=90, phase=phase
    )
    assert (
        control.permission_loss(state(status=status), now=datetime(2026, 9, 8, tzinfo=UTC))
        == InterruptionReason.LEASE_LOST
    )


@pytest.mark.parametrize("status", ["completed", "awaiting_approval"])
def test_own_finalisation_survives_committed_status(status: str) -> None:
    control = ExecutionControl(
        uuid4(),
        uuid4(),
        uuid4(),
        "owner",
        deadline=100,
        lease_deadline=90,
        phase=ExecutionPhase.FINALISING,
    )
    assert (
        control.permission_loss(state(status=status), now=datetime(2026, 9, 8, tzinfo=UTC)) is None
    )
    assert (
        control.permission_loss(
            state(status=status, owner="replacement"), now=datetime(2026, 9, 8, tzinfo=UTC)
        )
        == InterruptionReason.LEASE_LOST
    )


def test_continuation_clock_includes_queue_and_intersects_root() -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)
    root = ExecutionControl.from_claim(
        run_id=uuid4(),
        workspace_id=uuid4(),
        user_id=uuid4(),
        owner_instance_id="root",
        started_at=now - timedelta(seconds=100),
        lease_expires_at=now + timedelta(seconds=90),
        now=now,
        monotonic_now=50,
        max_duration=1200,
    )
    assert root.deadline == 1150
    child = ExecutionControl.from_claim(
        run_id=uuid4(),
        workspace_id=root.workspace_id,
        user_id=root.user_id,
        owner_instance_id="child",
        started_at=now,
        lease_expires_at=now + timedelta(seconds=90),
        now=now,
        monotonic_now=50,
        max_duration=1200,
        root=root,
    )
    assert child.deadline == root.deadline


def test_interruption_preserves_first_reason() -> None:
    control = ExecutionControl(uuid4(), uuid4(), uuid4(), "owner", deadline=100, lease_deadline=90)
    control.interrupt(InterruptionReason.DURATION_EXPIRED)
    control.interrupt(InterruptionReason.LEASE_LOST)
    assert control.reason == InterruptionReason.DURATION_EXPIRED


async def test_released_invocation_cannot_authorise_another_effect(monkeypatch):
    from services.agents.runtime.execution_control import ExecutionInterruptedError
    from tests.support.execution import build_execution_control

    control = build_execution_control()
    control.phase = ExecutionPhase.RELEASED

    async def unexpected_read(**_kwargs):
        pytest.fail("Released execution must stop before any database read")

    monkeypatch.setattr(
        "services.agents.runtime.execution_control.read_execution_states", unexpected_read
    )
    with pytest.raises(ExecutionInterruptedError) as stopped:
        await control.check_permission()
    assert stopped.value.reason == InterruptionReason.LEASE_LOST
