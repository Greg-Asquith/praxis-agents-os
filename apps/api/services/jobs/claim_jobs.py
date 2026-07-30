# apps/api/services/jobs/claim_jobs.py

"""Claim generic background jobs for execution."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
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
    workspace_running_job = aliased(Job)
    workspace_running_counts = (
        select(
            workspace_running_job.workspace_id,
            func.count(workspace_running_job.id).label("running_count"),
        )
        .where(
            workspace_running_job.status == JOB_STATUS_RUNNING,
            workspace_running_job.workspace_id.is_not(None),
        )
        .group_by(workspace_running_job.workspace_id)
        .subquery()
    )
    user_running_job = aliased(Job)
    user_running_counts = (
        select(
            user_running_job.concurrency_user_id,
            func.count(user_running_job.id).label("running_count"),
        )
        .where(
            user_running_job.status == JOB_STATUS_RUNNING,
            user_running_job.concurrency_user_id.is_not(None),
        )
        .group_by(user_running_job.concurrency_user_id)
        .subquery()
    )
    concurrency_limit = settings.JOBS_WORKSPACE_CONCURRENCY_LIMIT
    running_count = func.coalesce(
        workspace_running_counts.c.running_count,
        user_running_counts.c.running_count,
        0,
    )
    has_no_concurrency_owner = and_(
        Job.workspace_id.is_(None),
        Job.concurrency_user_id.is_(None),
    )
    ranked_pending_jobs = (
        select(
            Job.id.label("job_id"),
            running_count.label("running_count"),
            func.row_number()
            .over(
                partition_by=(Job.workspace_id, Job.concurrency_user_id),
                order_by=(Job.priority, Job.run_after, Job.created_at, Job.id),
            )
            .label("owner_pending_rank"),
        )
        .outerjoin(
            workspace_running_counts,
            Job.workspace_id == workspace_running_counts.c.workspace_id,
        )
        .outerjoin(
            user_running_counts,
            Job.concurrency_user_id == user_running_counts.c.concurrency_user_id,
        )
        .where(
            Job.status == JOB_STATUS_PENDING,
            Job.run_after <= now_utc,
            or_(
                has_no_concurrency_owner,
                running_count < concurrency_limit,
            ),
        )
        .subquery()
    )
    result = await db.execute(
        select(Job)
        .join(ranked_pending_jobs, Job.id == ranked_pending_jobs.c.job_id)
        .where(
            or_(
                and_(
                    Job.workspace_id.is_(None),
                    Job.concurrency_user_id.is_(None),
                ),
                ranked_pending_jobs.c.owner_pending_rank
                <= concurrency_limit - ranked_pending_jobs.c.running_count,
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
