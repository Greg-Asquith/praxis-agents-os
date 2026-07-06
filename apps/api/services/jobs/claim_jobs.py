# apps/api/services/jobs/claim_jobs.py

"""Claim generic background jobs for execution."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.settings import settings
from models.jobs import Job
from services.jobs.count_jobs import count_in_flight_jobs
from services.jobs.domain import JOB_STATUS_PENDING, JOB_STATUS_RUNNING

logger = logging.getLogger(__name__)


async def claim_jobs(
    db: AsyncSession,
    *,
    owner_instance_id: str,
    now: datetime | None = None,
    batch_size: int | None = None,
    lock_ttl_seconds: int | None = None,
) -> list[Job]:
    """Claim due jobs with row locks so overlapping workers split work."""
    now_utc = now or datetime.now(UTC)
    running_job = aliased(Job)
    running_counts = (
        select(running_job.workspace_id, func.count(running_job.id).label("running_count"))
        .where(
            running_job.status == JOB_STATUS_RUNNING,
            running_job.workspace_id.is_not(None),
        )
        .group_by(running_job.workspace_id)
        .subquery()
    )
    workspace_limit = settings.JOBS_WORKSPACE_CONCURRENCY_LIMIT
    ranked_pending_jobs = (
        select(
            Job.id.label("job_id"),
            func.coalesce(running_counts.c.running_count, 0).label("running_count"),
            func.row_number()
            .over(
                partition_by=Job.workspace_id,
                order_by=(Job.priority, Job.run_after, Job.created_at, Job.id),
            )
            .label("workspace_pending_rank"),
        )
        .outerjoin(running_counts, Job.workspace_id == running_counts.c.workspace_id)
        .where(
            Job.status == JOB_STATUS_PENDING,
            Job.run_after <= now_utc,
            or_(
                Job.workspace_id.is_(None),
                running_counts.c.running_count.is_(None),
                running_counts.c.running_count < workspace_limit,
            ),
        )
        .subquery()
    )
    result = await db.execute(
        select(Job)
        .join(ranked_pending_jobs, Job.id == ranked_pending_jobs.c.job_id)
        .where(
            or_(
                Job.workspace_id.is_(None),
                ranked_pending_jobs.c.workspace_pending_rank
                <= workspace_limit - ranked_pending_jobs.c.running_count,
            ),
        )
        .order_by(Job.priority, Job.run_after, Job.created_at)
        .limit(batch_size or settings.JOBS_WORKER_BATCH_SIZE)
        .with_for_update(skip_locked=True, of=Job)
    )
    jobs = list(result.scalars().all())
    expires_at = now_utc + timedelta(seconds=lock_ttl_seconds or settings.JOBS_LOCK_TTL_SECONDS)

    for job in jobs:
        job.status = JOB_STATUS_RUNNING
        job.locked_by = owner_instance_id
        job.locked_at = now_utc
        job.lock_expires_at = expires_at
        job.attempts = (job.attempts or 0) + 1
        job.last_error_code = None
        job.last_error_message = None

    await db.flush()
    await _log_workspace_concurrency_warnings(db)
    return jobs


async def _log_workspace_concurrency_warnings(db: AsyncSession) -> None:
    counts = await count_in_flight_jobs(db)
    limit = settings.JOBS_WORKSPACE_CONCURRENCY_LIMIT
    for workspace_id, count in counts.items():
        if workspace_id is None or count <= limit:
            continue
        logger.warning(
            "Workspace in-flight job count exceeds configured warning threshold",
            extra={
                "workspace_id": str(workspace_id),
                "in_flight_jobs": count,
                "limit": limit,
            },
        )
