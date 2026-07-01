# apps/api/services/agent_schedules/finalize_schedule_run_execution.py

"""Finalize a scheduled run from its generic agent run status."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL as AGENT_RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED as AGENT_RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED as AGENT_RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED as AGENT_RUN_STATUS_FAILED,
    RUN_STATUS_PENDING as AGENT_RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING as AGENT_RUN_STATUS_RUNNING,
)
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_TERMINAL_FAILED,
    mark_run_completed,
    mark_run_terminal_failure_and_disable_schedule,
)
from services.conversations.prune_failed import prune_failed_empty_conversation_for_run
from utils.dates import normalize_utc_datetime

_TERMINAL_SCHEDULE_RUN_STATUSES = {
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_TERMINAL_FAILED,
}


async def finalize_schedule_run_execution(
    db: AsyncSession,
    *,
    schedule_run_id: UUID,
    agent_run_id: UUID,
    now: datetime | None = None,
) -> None:
    """Mirror a generic agent run terminal/suspended state onto its schedule run."""
    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    schedule_run = await _load_schedule_run_for_update(db, schedule_run_id)
    schedule = await _load_schedule_for_update(db, schedule_run.schedule_id)
    agent_run = await _load_agent_run_for_update(db, agent_run_id)

    if schedule_run.agent_run_id != agent_run.id:
        raise ConflictError(
            "Schedule run is linked to a different agent run",
            conflicting_resource="agent_schedule_run",
            details={
                "schedule_run_id": str(schedule_run.id),
                "schedule_run_agent_run_id": str(schedule_run.agent_run_id),
                "agent_run_id": str(agent_run.id),
            },
        )

    if schedule_run.status in _TERMINAL_SCHEDULE_RUN_STATUSES:
        return

    if agent_run.status == AGENT_RUN_STATUS_COMPLETED:
        mark_run_completed(schedule, schedule_run, now=now_utc)
        await db.flush()
        return

    if agent_run.status == AGENT_RUN_STATUS_AWAITING_APPROVAL:
        schedule_run.status = RUN_STATUS_AWAITING_APPROVAL
        schedule_run.claim_expires_at = None
        await db.flush()
        return

    if agent_run.status in {AGENT_RUN_STATUS_FAILED, AGENT_RUN_STATUS_CANCELLED}:
        await mark_run_terminal_failure_and_disable_schedule(
            db,
            schedule,
            schedule_run,
            now=now_utc,
            code=agent_run.error_code or _terminal_error_code(agent_run.status),
            message=agent_run.error_message or _terminal_error_message(agent_run.status),
        )
        if schedule_run.conversation_id is not None:
            await prune_failed_empty_conversation_for_run(
                db,
                conversation_id=schedule_run.conversation_id,
                run_id=agent_run.id,
                deleted_by_user_id=schedule_run.user_id,
            )
        await db.flush()
        return

    if agent_run.status in {AGENT_RUN_STATUS_PENDING, AGENT_RUN_STATUS_RUNNING}:
        raise ConflictError(
            "Agent run is still active and cannot finalize its schedule run",
            conflicting_resource="agent_run",
            details={
                "schedule_run_id": str(schedule_run.id),
                "agent_run_id": str(agent_run.id),
                "agent_run_status": agent_run.status,
            },
        )

    raise ConflictError(
        "Unknown agent run status for schedule finalization",
        conflicting_resource="agent_run",
        details={"agent_run_id": str(agent_run.id), "agent_run_status": agent_run.status},
    )


async def _load_schedule_run_for_update(
    db: AsyncSession,
    schedule_run_id: UUID,
) -> AgentScheduleRun:
    schedule_run = await db.scalar(
        select(AgentScheduleRun)
        .where(
            AgentScheduleRun.id == schedule_run_id,
            AgentScheduleRun.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if schedule_run is None:
        raise NotFoundError(
            "Schedule run not found",
            resource_type="agent_schedule_run",
            resource_id=str(schedule_run_id),
        )
    return schedule_run


async def _load_schedule_for_update(db: AsyncSession, schedule_id: UUID) -> AgentSchedule:
    schedule = await db.scalar(
        select(AgentSchedule)
        .where(
            AgentSchedule.id == schedule_id,
            AgentSchedule.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if schedule is None:
        raise NotFoundError(
            "Schedule not found",
            resource_type="agent_schedule",
            resource_id=str(schedule_id),
        )
    return schedule


async def _load_agent_run_for_update(db: AsyncSession, agent_run_id: UUID) -> AgentRun:
    agent_run = await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.id == agent_run_id,
            AgentRun.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if agent_run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(agent_run_id),
        )
    return agent_run


def _terminal_error_code(status: str) -> str:
    if status == AGENT_RUN_STATUS_CANCELLED:
        return "agent_run_cancelled"
    return "agent_run_failed"


def _terminal_error_message(status: str) -> str:
    if status == AGENT_RUN_STATUS_CANCELLED:
        return "Scheduled agent run was cancelled."
    return "Scheduled agent run failed."
