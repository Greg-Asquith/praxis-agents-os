# apps/api/services/agent_schedules/runs.py

"""Durable run-attempt state helpers for agent schedules."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import AgentSchedule, AgentScheduleRun
from services.agent_runs.domain import RunOutcome
from services.agent_schedules.domain import (
    RUN_STATUS_CANCELLED,
    RUN_STATUS_CLAIMED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RETRYABLE_FAILED,
    RUN_STATUS_TERMINAL_FAILED,
    ScheduleConfig,
    calculate_next_run,
    can_transition_schedule_run,
)
from services.agent_schedules.utils import latest_schedule_run_subquery
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from utils.dates import normalize_utc_datetime

logger = logging.getLogger(__name__)

DEFAULT_CLAIM_TTL_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BATCH_SIZE = 50
MAX_ERROR_MESSAGE_LENGTH = 1000


@dataclass(frozen=True)
class ClaimedScheduleRun:
    """A schedule and claimed attempt ready for worker submission."""

    schedule: AgentSchedule
    run: AgentScheduleRun


def schedule_health_from_run(
    run: AgentScheduleRun | None,
    *,
    outcome: RunOutcome | None = None,
) -> str:
    """Return a compact health label for schedule list/detail responses."""

    if run is None:
        return "healthy"
    if outcome in {"gate_failed", "budget_exhausted"}:
        return "needs_attention"
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

    latest_runs = latest_schedule_run_subquery(schedule_ids=schedule_ids)
    result = await db.execute(
        select(AgentScheduleRun)
        .options(selectinload(AgentScheduleRun.agent_run))
        .join(latest_runs, latest_runs.c.id == AgentScheduleRun.id)
    )
    return {run.schedule_id: run for run in result.scalars()}


async def transition_schedule_run(
    db: AsyncSession,
    run: AgentScheduleRun,
    target: str,
) -> None:
    """Move a schedule run to target under its row lock, or raise ConflictError.

    Callers lock the schedule before calling, so locks are always taken schedule then run.
    """
    await db.flush()
    await db.refresh(run, with_for_update=True)
    if not can_transition_schedule_run(run.status, target):
        raise ConflictError(
            f"Cannot move schedule run from {run.status!r} to {target!r}",
            conflicting_resource="agent_schedule_run",
            details={"schedule_run_id": str(run.id), "from": run.status, "to": target},
        )
    run.status = target


async def lock_schedule_and_run(
    db: AsyncSession,
    schedule_run_id: UUID,
) -> tuple[AgentSchedule, AgentScheduleRun]:
    """Lock a schedule run's schedule, then the run, matching the claim's lock order."""

    schedule_id = await db.scalar(
        select(AgentScheduleRun.schedule_id).where(
            AgentScheduleRun.id == schedule_run_id,
            AgentScheduleRun.deleted == False,  # noqa: E712
        )
    )
    schedule = None
    if schedule_id is not None:
        schedule = await db.scalar(
            select(AgentSchedule)
            .where(AgentSchedule.id == schedule_id, AgentSchedule.deleted == False)  # noqa: E712
            .with_for_update()
        )
    if schedule is None:
        raise NotFoundError(
            "Schedule run not found",
            resource_type="agent_schedule_run",
            resource_id=str(schedule_run_id),
        )
    schedule_run = await db.scalar(
        select(AgentScheduleRun)
        .where(AgentScheduleRun.id == schedule_run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if schedule_run is None or schedule_run.deleted:
        raise NotFoundError(
            "Schedule run not found",
            resource_type="agent_schedule_run",
            resource_id=str(schedule_run_id),
        )
    return schedule, schedule_run


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


async def _claim_run(
    db: AsyncSession,
    run: AgentScheduleRun,
    *,
    now: datetime,
    claim_ttl_seconds: int,
) -> None:
    await transition_schedule_run(db, run, RUN_STATUS_CLAIMED)
    run.claim_token = uuid4()
    run.claimed_at = now
    run.claim_expires_at = now + timedelta(seconds=claim_ttl_seconds)
    run.attempt_count = (run.attempt_count or 0) + 1
    run.last_error_code = None
    run.last_error_message = None
    run.failed_at = None


def _config_from_schedule(schedule: AgentSchedule) -> ScheduleConfig:
    """Build a timing config from a persisted schedule row."""

    return ScheduleConfig(
        schedule_type=schedule.schedule_type,
        cron_expression=schedule.cron_expression,
        interval_minutes=schedule.interval_minutes,
        run_once_at=schedule.run_once_at,
        timezone=schedule.timezone,
    )


def _advance_schedule(schedule: AgentSchedule, *, now: datetime) -> None:
    schedule.last_run_at = now
    if not schedule.is_active:
        # Paused while the run was going: stay dormant until someone enables it.
        schedule.next_run_at = None
        return

    # Advance from the end time so a backlogged worker fires once, not through every missed slot.
    next_run = calculate_next_run(_config_from_schedule(schedule), basis=now, repeat_once=False)
    if next_run is None:
        # No further occurrence (once schedules): retire so the scanner stops selecting it.
        schedule.is_active = False
    schedule.next_run_at = next_run


async def mark_run_completed(
    db: AsyncSession,
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
) -> None:
    """Mark a run completed and advance or retire its schedule's next fire time."""

    await transition_schedule_run(db, run, RUN_STATUS_COMPLETED)
    run.completed_at = now
    run.claim_expires_at = None
    run.last_error_code = None
    run.last_error_message = None
    _advance_schedule(schedule, now=now)


async def mark_run_cancelled(
    db: AsyncSession,
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
) -> None:
    """Record a stopped run; stopping one run doesn't pause its schedule."""

    await transition_schedule_run(db, run, RUN_STATUS_CANCELLED)
    run.claim_expires_at = None
    _advance_schedule(schedule, now=now)


async def mark_run_terminal_failure_and_disable_schedule(
    db: AsyncSession,
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
    code: str,
    message: str,
) -> None:
    """Mark a schedule run terminal, disable its schedule, and audit the disable."""
    await transition_schedule_run(db, run, RUN_STATUS_TERMINAL_FAILED)
    run.failed_at = now
    run.last_error_code = code
    run.last_error_message = sanitize_error_message(message)
    run.claim_expires_at = None
    schedule.is_active = False
    schedule.next_run_at = None
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


def _run_is_claimable(run: AgentScheduleRun, *, now: datetime) -> bool:
    if run.status in {RUN_STATUS_PENDING, RUN_STATUS_RETRYABLE_FAILED}:
        return True
    if run.status != RUN_STATUS_CLAIMED:
        return False
    if run.claim_expires_at is None:
        # A claim always carries an expiry; re-claiming would inflate attempt_count without cause.
        logger.error("Claimed run %s has no claim_expires_at; skipping re-claim", run.id)
        return False
    return run.claim_expires_at <= now


async def claim_due_schedule_runs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    claim_ttl_seconds: int = DEFAULT_CLAIM_TTL_SECONDS,
) -> list[ClaimedScheduleRun]:
    """Claim due schedule fire times with row locks so overlapping workers split work."""

    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    current_run = aliased(AgentScheduleRun)

    result = await db.execute(
        select(AgentSchedule)
        .options(selectinload(AgentSchedule.agent))
        .outerjoin(
            current_run,
            and_(
                current_run.schedule_id == AgentSchedule.id,
                current_run.scheduled_for == AgentSchedule.next_run_at,
                current_run.deleted == False,  # noqa: E712
            ),
        )
        .where(
            AgentSchedule.is_active == True,  # noqa: E712
            AgentSchedule.deleted == False,  # noqa: E712
            AgentSchedule.next_run_at <= now_utc,
            or_(
                current_run.id.is_(None),
                current_run.status.in_({RUN_STATUS_PENDING, RUN_STATUS_RETRYABLE_FAILED}),
                and_(
                    current_run.status == RUN_STATUS_CLAIMED,
                    current_run.claim_expires_at.is_not(None),
                    current_run.claim_expires_at <= now_utc,
                ),
            ),
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

        # The run row may have moved since the scan; check it before touching it.
        if not _run_is_claimable(run, now=now_utc):
            continue

        agent = schedule.agent
        if agent is None or agent.deleted or not agent.is_active:
            missing = agent is None or agent.deleted
            await mark_run_terminal_failure_and_disable_schedule(
                db,
                schedule,
                run,
                now=now_utc,
                code="agent_unavailable" if missing else "agent_inactive",
                message=(
                    "Scheduled agent is missing or deleted"
                    if missing
                    else "Scheduled agent is inactive"
                ),
            )
            continue

        await _claim_run(db, run, now=now_utc, claim_ttl_seconds=claim_ttl_seconds)
        claimed.append(ClaimedScheduleRun(schedule=schedule, run=run))

    await db.flush()
    return claimed


async def record_retryable_failure(
    db: AsyncSession,
    schedule: AgentSchedule,
    run: AgentScheduleRun,
    *,
    now: datetime,
    code: str,
    message: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Record a failure before execution: retry it, or stop the schedule once attempts run out."""

    if (run.attempt_count or 0) >= max_attempts:
        await mark_run_terminal_failure_and_disable_schedule(
            db, schedule, run, now=now, code=code, message=message
        )
        return

    await transition_schedule_run(db, run, RUN_STATUS_RETRYABLE_FAILED)
    run.failed_at = now
    run.claim_expires_at = None
    run.last_error_code = code
    run.last_error_message = sanitize_error_message(message)
