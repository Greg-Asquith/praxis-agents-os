# apps/api/services/agent_schedules/runs.py

"""Durable run-attempt state helpers for agent schedules."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.agent import AgentSchedule, AgentScheduleRun
from services.agent_schedules.domain import ScheduleConfig, calculate_next_run
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from utils.dates import normalize_utc_datetime

logger = logging.getLogger(__name__)

RUN_STATUS_PENDING = "pending"
RUN_STATUS_CLAIMED = "claimed"
RUN_STATUS_ACCEPTED = "accepted"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_AWAITING_APPROVAL = "awaiting_approval"
RUN_STATUS_RETRYABLE_FAILED = "retryable_failed"
RUN_STATUS_TERMINAL_FAILED = "terminal_failed"
RUN_STATUS_CANCELLED = "cancelled"

NON_CLAIMABLE_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_ACCEPTED,
        RUN_STATUS_RUNNING,
        RUN_STATUS_COMPLETED,
        RUN_STATUS_AWAITING_APPROVAL,
        RUN_STATUS_TERMINAL_FAILED,
        RUN_STATUS_CANCELLED,
    }
)

CLAIMABLE_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_PENDING,
        RUN_STATUS_RETRYABLE_FAILED,
        RUN_STATUS_CLAIMED,
    }
)

DEFAULT_CLAIM_TTL_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BATCH_SIZE = 50
MAX_ERROR_MESSAGE_LENGTH = 1000


@dataclass(frozen=True)
class ClaimedScheduleRun:
    """A schedule and claimed attempt ready for worker submission."""

    schedule: AgentSchedule
    run: AgentScheduleRun


def schedule_health_from_run(run: AgentScheduleRun | None) -> str:
    """Return a compact health label for schedule list/detail responses."""

    if run is None:
        return "healthy"
    if run.status == RUN_STATUS_RETRYABLE_FAILED:
        return "retrying"
    if run.status == RUN_STATUS_TERMINAL_FAILED:
        return "needs_attention"
    if run.status == RUN_STATUS_CANCELLED:
        return "cancelled"
    return "healthy"


def sanitize_error_message(message: str | None) -> str | None:
    """Persist concise operational error text without oversized payload dumps."""

    if message is None:
        return None
    normalized = " ".join(message.split())
    if not normalized:
        return None
    return normalized[:MAX_ERROR_MESSAGE_LENGTH]


async def get_latest_runs_by_schedule_ids(
    db: AsyncSession,
    schedule_ids: list[UUID],
) -> dict[UUID, AgentScheduleRun]:
    """Load the latest non-deleted run attempt for each schedule id."""

    if not schedule_ids:
        return {}

    result = await db.execute(
        select(AgentScheduleRun)
        .distinct(AgentScheduleRun.schedule_id)
        .where(
            AgentScheduleRun.schedule_id.in_(schedule_ids),
            AgentScheduleRun.deleted == False,  # noqa: E712
        )
        .order_by(
            AgentScheduleRun.schedule_id,
            AgentScheduleRun.scheduled_for.desc(),
            AgentScheduleRun.created_at.desc(),
        )
    )
    return {run.schedule_id: run for run in result.scalars()}


async def _get_or_create_run_for_schedule(
    db: AsyncSession,
    schedule: AgentSchedule,
) -> AgentScheduleRun | None:
    scheduled_for = normalize_utc_datetime(schedule.next_run_at, field="next_run_at")
    if scheduled_for is None:
        return None

    result = await db.execute(
        select(AgentScheduleRun)
        .where(
            AgentScheduleRun.schedule_id == schedule.id,
            AgentScheduleRun.scheduled_for == scheduled_for,
            AgentScheduleRun.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    run = result.scalar_one_or_none()
    if run is not None:
        return run

    run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=schedule.workspace_id,
        user_id=schedule.user_id,
        agent_id=schedule.agent_id,
        scheduled_for=scheduled_for,
        status=RUN_STATUS_PENDING,
    )
    db.add(run)
    await db.flush()
    return run


def _claim_run(
    run: AgentScheduleRun,
    *,
    now: datetime,
    claim_ttl_seconds: int,
) -> None:
    run.status = RUN_STATUS_CLAIMED
    run.claim_token = uuid4()
    run.claimed_at = now
    run.claim_expires_at = now + timedelta(seconds=claim_ttl_seconds)
    run.attempt_count = (run.attempt_count or 0) + 1
    run.last_error_code = None
    run.last_error_message = None
    run.failed_at = None


def mark_run_terminal_failure(
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
    code: str,
    message: str,
) -> None:
    """Mark a run terminal and stop the schedule until user action."""

    run.status = RUN_STATUS_TERMINAL_FAILED
    run.failed_at = now
    run.last_error_code = code
    run.last_error_message = sanitize_error_message(message)
    run.claim_expires_at = None
    schedule.is_active = False
    schedule.next_run_at = None


def _config_from_schedule(schedule: AgentSchedule) -> ScheduleConfig:
    """Build a timing config from a persisted schedule row."""

    return ScheduleConfig(
        schedule_type=schedule.schedule_type,
        cron_expression=schedule.cron_expression,
        interval_minutes=schedule.interval_minutes,
        run_once_at=schedule.run_once_at,
        timezone=schedule.timezone,
    )


def mark_run_completed(
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
) -> None:
    """Mark a run completed and advance or retire its schedule's next fire time."""

    run.status = RUN_STATUS_COMPLETED
    run.completed_at = now
    run.claim_expires_at = None
    run.last_error_code = None
    run.last_error_message = None
    schedule.last_run_at = now

    # Advance from completion time so a backlogged worker fires once, not through every missed slot.
    next_run = calculate_next_run(_config_from_schedule(schedule), basis=now, repeat_once=False)
    if next_run is None:
        # No further occurrence (once schedules): retire so the scanner stops selecting it.
        schedule.is_active = False
        schedule.next_run_at = None
    else:
        schedule.next_run_at = next_run


async def _fail_run_terminally(
    db: AsyncSession,
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
    code: str,
    message: str,
) -> None:
    """Mark a run terminal (disabling its schedule) and audit the disable."""
    mark_run_terminal_failure(schedule, run, now=now, code=code, message=message)
    await safe_record_operation_audit_event(
        db,
        workspace_id=schedule.workspace_id,
        action=AuditAction.DISABLE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id=schedule.id,
        status=AuditStatus.FAILURE,
        actor_type=AuditActorType.SYSTEM,
        actor_display="Scheduler",
        requested_by_user_id=schedule.user_id,
        details={
            "run_id": str(run.id),
            "error_code": code,
            "error_message": message,
            "attempt_count": run.attempt_count,
        },
    )


async def claim_due_schedule_runs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    claim_ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS,
) -> list[ClaimedScheduleRun]:
    """Claim due schedule fire times with row locks so overlapping workers split work."""

    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)

    result = await db.execute(
        select(AgentSchedule)
        .options(selectinload(AgentSchedule.agent))
        .where(
            AgentSchedule.is_active == True,  # noqa: E712
            AgentSchedule.deleted == False,  # noqa: E712
            AgentSchedule.next_run_at <= now_utc,
        )
        .order_by(AgentSchedule.next_run_at, AgentSchedule.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=AgentSchedule)
    )
    due_schedules = result.scalars().all()

    claimed: list[ClaimedScheduleRun] = []
    for schedule in due_schedules:
        run = await _get_or_create_run_for_schedule(db, schedule)
        if run is None:
            continue

        agent = schedule.agent
        if agent is None or agent.deleted:
            await _fail_run_terminally(
                db,
                schedule,
                run,
                now=now_utc,
                code="agent_unavailable",
                message="Scheduled agent is missing or deleted",
            )
            continue

        if not agent.is_active:
            await _fail_run_terminally(
                db,
                schedule,
                run,
                now=now_utc,
                code="agent_inactive",
                message="Scheduled agent is inactive",
            )
            continue

        if run.status in NON_CLAIMABLE_RUN_STATUSES:
            continue
        if run.status not in CLAIMABLE_RUN_STATUSES:
            continue
        if run.status == RUN_STATUS_CLAIMED:
            if run.claim_expires_at is None:
                # A claimed run must always carry an expiry; treat a missing one
                # as a data-integrity issue and skip rather than silently
                # re-claiming (which would inflate attempt_count without cause).
                logger.error("Claimed run %s has no claim_expires_at; skipping re-claim", run.id)
                continue
            if run.claim_expires_at > now_utc:
                continue

        _claim_run(run, now=now_utc, claim_ttl_seconds=claim_ttl_seconds)
        claimed.append(ClaimedScheduleRun(schedule=schedule, run=run))

    await db.flush()
    return claimed


def mark_run_retryable_failure(
    run: AgentScheduleRun,
    *,
    now: datetime,
    code: str,
    message: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> bool:
    """Record a retryable trigger failure, returning True when retry cap is exhausted."""

    run.failed_at = now
    run.claim_expires_at = None
    run.last_error_code = code
    run.last_error_message = sanitize_error_message(message)

    if (run.attempt_count or 0) >= max_attempts:
        run.status = RUN_STATUS_TERMINAL_FAILED
        return True

    run.status = RUN_STATUS_RETRYABLE_FAILED
    return False
