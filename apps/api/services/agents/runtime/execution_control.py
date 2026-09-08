# apps/api/services/agents/runtime/execution_control.py

"""Tracks local invocation phases, permission, and monotonic deadlines."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.execution_state import ExecutionState, read_execution_states

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps


class ExecutionPhase(StrEnum):
    QUEUED = "queued"
    EXECUTING = "executing"
    FINALISING = "finalising"
    RELEASED = "released"


class InterruptionReason(StrEnum):
    REQUESTED_CANCELLATION = "agent_run_cancel_requested"
    DURATION_EXPIRED = "run_duration_expired"
    LEASE_LOST = "run_lease_lost"
    PARENT_TERMINATED = "run_parent_terminated"
    PROCESS_SHUTDOWN = "run_process_shutdown"


class ExecutionInterruptedError(Exception):
    """Stops execution with an allowlisted lifecycle cause."""

    def __init__(self, reason: InterruptionReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


@dataclass
class ExecutionControl:
    """Owns one continuation clock independently of ORM object refreshes."""

    run_id: UUID
    workspace_id: UUID
    user_id: UUID
    owner_instance_id: str
    deadline: float
    lease_deadline: float
    phase: ExecutionPhase = ExecutionPhase.QUEUED
    root: ExecutionControl | None = None
    reason: InterruptionReason | None = None

    @classmethod
    def from_claim(
        cls,
        *,
        run_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        owner_instance_id: str,
        started_at: datetime,
        lease_expires_at: datetime,
        max_duration: float,
        now: datetime,
        monotonic_now: float,
        root: ExecutionControl | None = None,
    ) -> ExecutionControl:
        """Derives local deadlines once from the durable admission timestamps."""
        deadline = monotonic_now + max_duration - (now - started_at).total_seconds()
        return cls(
            run_id,
            workspace_id,
            user_id,
            owner_instance_id,
            min(deadline, root.deadline) if root else deadline,
            monotonic_now + (lease_expires_at - now).total_seconds(),
            root=root,
        )

    def interrupt(self, reason: InterruptionReason, task: asyncio.Task | None = None) -> None:
        """Retains the first stop cause and requests local cancellation once."""
        if self.reason is None:
            self.reason = reason
            if task is not None and not task.done():
                task.cancel(reason.value)

    def permission_loss(
        self, state: ExecutionState | None, *, now: datetime
    ) -> InterruptionReason | None:
        """Checks durable ownership with an exemption for own finalisation."""
        if state is None or state.owner_instance_id != self.owner_instance_id:
            return InterruptionReason.LEASE_LOST
        if state.status == "cancelled":
            return InterruptionReason.REQUESTED_CANCELLATION
        if self.phase == ExecutionPhase.FINALISING and state.status in {
            "completed",
            "awaiting_approval",
        }:
            return None
        if state.status not in {"pending", "running"}:
            return InterruptionReason.LEASE_LOST
        if state.lease_expires_at is None or state.lease_expires_at <= now:
            return InterruptionReason.LEASE_LOST
        return None

    async def check_permission(self) -> None:
        """Requires a fresh own lease and a live controlling root before the next effect."""
        if self.phase == ExecutionPhase.RELEASED:
            self.interrupt(InterruptionReason.LEASE_LOST)
        if self.reason is not None:
            raise ExecutionInterruptedError(self.reason)
        if (
            self.phase in {ExecutionPhase.QUEUED, ExecutionPhase.EXECUTING}
            and asyncio.get_running_loop().time() >= self.deadline
        ):
            self.interrupt(InterruptionReason.DURATION_EXPIRED)
            raise ExecutionInterruptedError(InterruptionReason.DURATION_EXPIRED)
        root = self.root
        run_ids = (self.run_id, root.run_id) if root else (self.run_id,)
        try:
            async with asyncio.timeout_at(self.lease_deadline):
                states = await read_execution_states(
                    run_ids=run_ids, workspace_id=self.workspace_id, user_id=self.user_id
                )
        except Exception as exc:
            self.interrupt(InterruptionReason.LEASE_LOST)
            raise ExecutionInterruptedError(InterruptionReason.LEASE_LOST) from exc
        now = datetime.now(UTC)
        reason = self.permission_loss(states.get(self.run_id), now=now)
        if root:
            root_state = states.get(root.run_id)
            if (
                root.reason
                or root_state is None
                or root_state.status not in {"pending", "running"}
                or root_state.owner_instance_id != root.owner_instance_id
                or root_state.lease_expires_at is None
                or root_state.lease_expires_at <= now
            ):
                reason = InterruptionReason.PARENT_TERMINATED
        if reason is not None:
            self.interrupt(reason)
            raise ExecutionInterruptedError(reason)


def execution_control_for_run(
    run: AgentRun, *, root: ExecutionControl | None = None
) -> ExecutionControl:
    """Captures the claimed continuation without resetting time at worker entry."""
    if run.owner_instance_id is None or run.lease_expires_at is None:
        raise ExecutionInterruptedError(InterruptionReason.LEASE_LOST)
    return ExecutionControl.from_claim(
        run_id=run.id,
        workspace_id=run.workspace_id,
        user_id=run.user_id,
        owner_instance_id=run.owner_instance_id,
        started_at=run.started_at or run.created_at,
        lease_expires_at=run.lease_expires_at,
        max_duration=settings.AGENT_RUN_MAX_DURATION_SECONDS,
        now=datetime.now(UTC),
        monotonic_now=asyncio.get_running_loop().time(),
        root=root,
    )


async def check_execution_permission(deps: RuntimeDeps) -> None:
    """Checks an admitted invocation before a model or tool request."""
    if deps.execution_control is None:
        return
    try:
        await deps.execution_control.check_permission()
    except ExecutionInterruptedError as exc:
        if exc.reason == InterruptionReason.REQUESTED_CANCELLATION:
            raise asyncio.CancelledError(exc.reason.value) from exc
        raise
