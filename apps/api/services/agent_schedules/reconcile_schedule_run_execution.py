# apps/api/services/agent_schedules/reconcile_schedule_run_execution.py

"""Recover abandoned schedule execution rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent import AgentScheduleRun
from models.agent_run import AgentRun
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL as AGENT_RUN_STATUS_AWAITING_APPROVAL,
    TERMINAL_RUN_STATUSES,
)
from services.agent_schedules.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_RUNNING,
    SCHEDULE_EXECUTION_ABANDONED_ERROR_CODE,
)
from services.agent_schedules.finalize_schedule_run_execution import (
    finalize_schedule_run_execution,
)
from services.agent_schedules.runs import lock_schedule_and_run, record_retryable_failure
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
    # Read candidates without locks; each one is locked schedule then run before it changes.
    result = await db.execute(
        select(AgentScheduleRun)
        .outerjoin(AgentRun, AgentScheduleRun.agent_run_id == AgentRun.id)
        .where(
            AgentScheduleRun.deleted == False,  # noqa: E712
            or_(
                AgentScheduleRun.status == RUN_STATUS_RUNNING,
                and_(
                    AgentScheduleRun.status == RUN_STATUS_AWAITING_APPROVAL,
                    AgentRun.status.in_(TERMINAL_RUN_STATUSES),
                ),
            ),
        )
        .order_by(AgentScheduleRun.created_at)
        .limit(batch_size or DEFAULT_RECONCILE_BATCH_SIZE)
    )
    schedule_runs = list(result.scalars())

    reconciled = 0
    for schedule_run in schedule_runs:
        if schedule_run.agent_run_id is not None:
            if await _finalize_if_agent_run_ready(db, schedule_run=schedule_run, now=now_utc):
                reconciled += 1
            continue

        if await _mark_stale_pre_execution_failure(db, schedule_run=schedule_run, now=now_utc):
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

    try:
        await finalize_schedule_run_execution(
            db,
            schedule_run_id=schedule_run.id,
            agent_run_id=agent_run.id,
            now=now,
        )
    except ConflictError:
        # The agent run resumed after the scan; finalize refused before writing anything.
        return False
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
) -> bool:
    schedule, schedule_run = await lock_schedule_and_run(db, schedule_run.id)
    if schedule_run.status != RUN_STATUS_RUNNING or schedule_run.agent_run_id is not None:
        return False
    if not _schedule_run_without_agent_run_is_stale(schedule_run, now=now):
        return False

    await record_retryable_failure(
        db,
        schedule,
        schedule_run,
        now=now,
        code=SCHEDULE_EXECUTION_ABANDONED_ERROR_CODE,
        message="Schedule run was abandoned before an agent run was linked.",
        max_attempts=settings.AGENT_SCHEDULE_RUN_MAX_ATTEMPTS,
    )
    return True
