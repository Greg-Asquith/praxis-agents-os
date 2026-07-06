# apps/api/services/jobs/reclaim_stale_jobs.py

"""Reclaim generic jobs whose worker lease expired."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import JOB_STATUS_RUNNING
from services.jobs.finalize_job import finalize_job_failure


async def reclaim_stale_jobs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Move expired running jobs back to pending for another attempt."""
    now_utc = now or datetime.now(UTC)
    result = await db.execute(
        select(Job)
        .where(
            Job.status == JOB_STATUS_RUNNING,
            Job.lock_expires_at.is_not(None),
            Job.lock_expires_at < now_utc,
        )
        .with_for_update(skip_locked=True)
    )
    jobs = list(result.scalars().all())
    for job in jobs:
        await finalize_job_failure(
            db,
            job,
            code="lease_expired",
            message="Worker lease expired before job completed",
            now=now_utc,
        )
    return len(jobs)
