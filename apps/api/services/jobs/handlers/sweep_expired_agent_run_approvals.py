# apps/api/services/jobs/handlers/sweep_expired_agent_run_approvals.py

"""Expire parked agent-run approvals and clean their staged tool content."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_run import AgentRun
from models.jobs import Job
from services.agent_runs.staged_content_cleanup import (
    DELETE_STAGED_APPROVAL_CONTENT_KIND,
)
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.registry import job_handler
from utils.dates import normalize_utc_datetime

SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND = "agent_runs.sweep_expired_approvals"
APPROVAL_EXPIRED_ERROR_CODE = "approval_expired"
DEFAULT_APPROVAL_SWEEP_BATCH_SIZE = 100

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepExpiredApprovalsResult:
    """Summary of approval waits expired by one sweep."""

    expired_run_ids: list[UUID]

    @property
    def expired_count(self) -> int:
        return len(self.expired_run_ids)


@job_handler(kind=DELETE_STAGED_APPROVAL_CONTENT_KIND, timeout=120.0)
async def handle_delete_staged_approval_content(_db: AsyncSession, job: Job) -> None:
    """Delete staged approval content after the owning run is terminal."""
    workspace_id, run_id, content_refs = _parse_staged_content_cleanup_payload(job.payload)

    from services.agents.runtime.staged_tool_content import delete_staged_write_content

    for content_ref in content_refs:
        await delete_staged_write_content(
            workspace_id=workspace_id,
            run_id=run_id,
            content_ref=content_ref,
        )


@job_handler(kind=SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND, timeout=120.0)
async def handle_sweep_expired_agent_run_approvals(db: AsyncSession, job: Job) -> None:
    """Expire one batch and schedule the next sweep while expiry is enabled."""
    now = datetime.now(UTC)
    result = await sweep_expired_agent_run_approvals(db, now=now)
    if result.expired_count:
        logger.info(
            "Expired parked agent-run approvals",
            extra={"count": result.expired_count},
        )

    if settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS == 0:
        return

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-agent-run-approvals:{job.id}",
        run_after=now + timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS),
    )


async def sweep_expired_agent_run_approvals(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    expiry_days: int | None = None,
    batch_size: int = DEFAULT_APPROVAL_SWEEP_BATCH_SIZE,
) -> SweepExpiredApprovalsResult:
    """Fail one locked batch of approval waits older than the configured TTL."""
    from services.agent_runs.approval_expiry import (
        approval_family_deadline,
        has_live_approval_reservation,
    )
    from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
    from services.agent_runs.settle_run_family import lock_run_family, settle_run_family

    configured_days = (
        settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS if expiry_days is None else expiry_days
    )
    if configured_days < 0:
        raise ValueError("expiry_days must be greater than or equal to zero")
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if configured_days == 0:
        return SweepExpiredApprovalsResult(expired_run_ids=[])

    now_utc = normalize_utc_datetime(now, field="now") or datetime.now(UTC)
    cutoff = now_utc - timedelta(days=configured_days)
    expired_run_ids: list[UUID] = []
    visited: set[UUID] = set()
    while len(visited) < batch_size:
        run = await db.scalar(
            select(AgentRun)
            .where(
                AgentRun.deleted == False,  # noqa: E712
                AgentRun.status == RUN_STATUS_AWAITING_APPROVAL,
                AgentRun.updated_at <= cutoff,
                AgentRun.id.not_in(visited),
            )
            .order_by(AgentRun.updated_at, AgentRun.id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if run is None:
            break

        visited.add(run.id)
        family = await lock_run_family(db, run_id=run.id)
        if not family:
            await db.commit()
            continue
        root = family[0]
        visited.update(item.id for item in family)
        if has_live_approval_reservation(root, family=family, now=now_utc):
            await db.commit()
            continue
        reservation = (root.metadata_json or {}).get("approval_continuation")
        deadline = approval_family_deadline(family, expiry_days=configured_days)
        if reservation is not None and root.status == "running":
            code = "agent_run_resume_requires_recovery"
            message = "The approved work stopped before its result could be confirmed."
        elif (
            root.status == RUN_STATUS_AWAITING_APPROVAL
            and deadline is not None
            and deadline <= now_utc
        ):
            code = APPROVAL_EXPIRED_ERROR_CODE
            message = (
                f"This approval expired after {configured_days} days, so the action wasn't taken. "
                "Send a new message to try again."
            )
        else:
            await db.commit()
            continue
        changed = await settle_run_family(
            db,
            run_id=root.id,
            error_code=code,
            error_message=message,
        )
        expired_run_ids.extend(item.id for item in changed)
        await db.commit()

    return SweepExpiredApprovalsResult(expired_run_ids=expired_run_ids)


async def ensure_agent_run_approval_sweep_job(db: AsyncSession) -> Job | None:
    """Ensure one approval-expiry sweep is in flight while expiry is enabled."""
    if settings.AGENT_RUN_APPROVAL_EXPIRY_DAYS == 0:
        return None

    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND,
        content_hash="sweep-agent-run-approvals:ensure",
        run_after=datetime.now(UTC),
    )


def _parse_staged_content_cleanup_payload(
    payload: dict[str, object],
) -> tuple[UUID, UUID, list[str]]:
    """Validate the durable cleanup payload before touching object storage."""
    try:
        workspace_id = UUID(str(payload["workspace_id"]))
        run_id = UUID(str(payload["run_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Staged approval cleanup payload has invalid identifiers") from exc

    raw_refs = payload.get("content_refs")
    if (
        not isinstance(raw_refs, list)
        or not raw_refs
        or not all(isinstance(value, str) for value in raw_refs)
    ):
        raise ValueError("Staged approval cleanup payload has invalid content refs")

    return workspace_id, run_id, list(dict.fromkeys(raw_refs))
