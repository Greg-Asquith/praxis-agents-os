# apps/api/services/agent_schedules/reconcile_schedule_run_execution.py

"""Recover abandoned schedule execution rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from services.agent_runs import reap_abandoned_runs
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL as AGENT_RUN_STATUS_AWAITING_APPROVAL,
    TERMINAL_RUN_STATUSES,
)
from services.agent_schedules.finalize_schedule_run_execution import (
    finalize_schedule_run_execution,
)
from services.agent_schedules.runs import (
    RUN_STATUS_ACCEPTED,
    RUN_STATUS_RUNNING,
    mark_run_retryable_failure,
    mark_run_terminal_failure_and_disable_schedule,
)
from utils.dates import normalize_utc_datetime

DEFAULT_RECONCILE_BATCH_SIZE = 100


async def reconcile_schedule_run_execution(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int | None = None,
) -> int:
    """Reconcile stale schedule execution state from generic run state."""
    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    await reap_abandoned_runs(db, now=now_utc)

    result = await db.execute(
        select(AgentScheduleRun)
        .where(
            AgentScheduleRun.deleted == False,  # noqa: E712
            AgentScheduleRun.status.in_({RUN_STATUS_ACCEPTED, RUN_STATUS_RUNNING}),
        )
        .order_by(AgentScheduleRun.created_at)
        .limit(batch_size or DEFAULT_RECONCILE_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    schedule_runs = list(result.scalars())

    reconciled = 0
    for schedule_run in schedule_runs:
        if schedule_run.agent_run_id is not None:
            if await _finalize_if_agent_run_ready(db, schedule_run=schedule_run, now=now_utc):
                reconciled += 1
            continue

        if not _schedule_run_without_agent_run_is_stale(schedule_run, now=now_utc):
            continue

        await _mark_stale_pre_execution_failure(db, schedule_run=schedule_run, now=now_utc)
        reconciled += 1

    await db.flush()
    return reconciled


async def _finalize_if_agent_run_ready(
    db: AsyncSession,
    *,
    schedule_run: AgentScheduleRun,
    now: datetime,
) -> bool:
    agent_run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == schedule_run.agent_run_id,
            AgentRun.deleted == False,  # noqa: E712
        )
    )
    if agent_run is None:
        return False
    if agent_run.status not in TERMINAL_RUN_STATUSES | {AGENT_RUN_STATUS_AWAITING_APPROVAL}:
        return False

    await finalize_schedule_run_execution(
        db,
        schedule_run_id=schedule_run.id,
        agent_run_id=agent_run.id,
        now=now,
    )
    return True


def _schedule_run_without_agent_run_is_stale(
    schedule_run: AgentScheduleRun,
    *,
    now: datetime,
) -> bool:
    if schedule_run.claim_expires_at is not None and schedule_run.claim_expires_at <= now:
        return True
    if schedule_run.accepted_at is None:
        return False
    accepted_cutoff = now - timedelta(seconds=settings.AGENT_SCHEDULE_RUN_CLAIM_TTL_SECONDS)
    return schedule_run.accepted_at <= accepted_cutoff


async def _mark_stale_pre_execution_failure(
    db: AsyncSession,
    *,
    schedule_run: AgentScheduleRun,
    now: datetime,
) -> None:
    schedule = await db.scalar(
        select(AgentSchedule)
        .where(
            AgentSchedule.id == schedule_run.schedule_id,
            AgentSchedule.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    if schedule is None:
        return

    exhausted = mark_run_retryable_failure(
        schedule_run,
        now=now,
        code="schedule_execution_abandoned",
        message="Schedule run was abandoned before an agent run was linked.",
        max_attempts=settings.AGENT_SCHEDULE_RUN_MAX_ATTEMPTS,
    )
    if exhausted:
        await mark_run_terminal_failure_and_disable_schedule(
            db,
            schedule,
            schedule_run,
            now=now,
            code="schedule_execution_abandoned",
            message="Schedule run exceeded setup retry attempts before execution.",
        )
