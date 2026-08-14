# apps/api/services/agent_runs/reap_abandoned.py

"""Fail abandoned pending/running agent runs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs.domain import RUN_STATUS_PENDING, RUN_STATUS_RUNNING
from services.agent_runs.fail import fail_agent_run
from services.agent_runs.staged_content_cleanup import (
    enqueue_staged_approval_content_cleanup,
)
from services.agents.runtime.approval_state import clear_suspended_run_metadata
from utils.dates import normalize_utc_datetime

DEFAULT_REAPER_BATCH_SIZE = 100
RUN_ABANDONED_ERROR_CODE = "run_abandoned"


@dataclass(frozen=True)
class ReapAbandonedRunsResult:
    """Summary of abandoned runs transitioned by one sweep."""

    failed_run_ids: list[UUID]

    @property
    def failed_count(self) -> int:
        return len(self.failed_run_ids)


async def reap_abandoned_runs(
    db: AsyncSession,
    *,
    run_id: UUID | None = None,
    conversation_id: UUID | None = None,
    now: datetime | None = None,
    batch_size: int = DEFAULT_REAPER_BATCH_SIZE,
    pending_grace_seconds: int | None = None,
    max_duration_seconds: int | None = None,
) -> ReapAbandonedRunsResult:
    """Fail pending/running runs whose lease/grace/deadline has expired.

    Scope by ``run_id`` or ``conversation_id`` for lazy on-read reaping; omit both
    for the startup/periodic batch sweep.
    """
    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    pending_grace = pending_grace_seconds or settings.AGENT_RUN_PENDING_GRACE_SECONDS
    max_duration = max_duration_seconds or settings.AGENT_RUN_MAX_DURATION_SECONDS
    pending_cutoff = now_utc - timedelta(seconds=pending_grace)
    hard_deadline_cutoff = now_utc - timedelta(seconds=max_duration)

    stmt = (
        select(AgentRun)
        .where(
            AgentRun.deleted == False,  # noqa: E712
            AgentRun.status.in_({RUN_STATUS_PENDING, RUN_STATUS_RUNNING}),
            _abandoned_condition(
                now_utc=now_utc,
                pending_cutoff=pending_cutoff,
                hard_deadline_cutoff=hard_deadline_cutoff,
            ),
        )
        .order_by(AgentRun.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=AgentRun)
    )
    if run_id is not None:
        stmt = stmt.where(AgentRun.id == run_id)
    if conversation_id is not None:
        stmt = stmt.where(AgentRun.conversation_id == conversation_id)

    result = await db.execute(stmt)
    runs = list(result.scalars())
    failed_run_ids: list[UUID] = []
    for run in runs:
        await enqueue_staged_approval_content_cleanup(db, run=run)
        run.metadata_json = clear_suspended_run_metadata(run)
        await fail_agent_run(
            db,
            run,
            error_code=RUN_ABANDONED_ERROR_CODE,
            error_message=_abandoned_message(run, now_utc=now_utc),
        )
        failed_run_ids.append(run.id)

    return ReapAbandonedRunsResult(failed_run_ids=failed_run_ids)


def _abandoned_condition(
    *,
    now_utc: datetime,
    pending_cutoff: datetime,
    hard_deadline_cutoff: datetime,
):
    stale_lease = and_(
        AgentRun.lease_expires_at.is_not(None),
        AgentRun.lease_expires_at <= now_utc,
    )
    stale_pending_without_lease = and_(
        AgentRun.status == RUN_STATUS_PENDING,
        AgentRun.lease_expires_at.is_(None),
        AgentRun.created_at <= pending_cutoff,
    )
    stale_running_without_lease = and_(
        AgentRun.status == RUN_STATUS_RUNNING,
        AgentRun.lease_expires_at.is_(None),
        AgentRun.started_at <= hard_deadline_cutoff,
    )
    past_started_deadline = and_(
        AgentRun.started_at.is_not(None),
        AgentRun.started_at <= hard_deadline_cutoff,
    )
    past_created_deadline = and_(
        AgentRun.started_at.is_(None),
        AgentRun.created_at <= hard_deadline_cutoff,
    )
    return or_(
        stale_lease,
        stale_pending_without_lease,
        stale_running_without_lease,
        past_started_deadline,
        past_created_deadline,
    )


def _abandoned_message(run: AgentRun, *, now_utc: datetime) -> str:
    # Only blame the lease when it actually lapsed; a fresh lease means the
    # run matched a duration deadline instead.
    lease = normalize_utc_datetime(run.lease_expires_at, field="lease_expires_at")
    if lease is not None and lease <= now_utc:
        return f"Agent run lease expired at {lease.isoformat()}"
    if run.status == RUN_STATUS_PENDING and run.lease_expires_at is None:
        return "Agent run stayed pending beyond the allowed grace period"
    return "Agent run exceeded the allowed maximum duration"
