# apps/api/services/jobs/renew_job_lease.py

"""Renew generic background job leases."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.domain import JOB_STATUS_RUNNING


async def renew_job_lease(
    db: AsyncSession,
    *,
    job_id: UUID,
    owner_instance_id: str,
    now: datetime | None = None,
    lock_ttl_seconds: float | None = None,
) -> bool:
    """Extends a live job lease when the caller still owns the running attempt."""
    now_utc = now or datetime.now(UTC)
    ttl_seconds = settings.JOBS_LOCK_TTL_SECONDS if lock_ttl_seconds is None else lock_ttl_seconds
    result = await db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JOB_STATUS_RUNNING,
            Job.locked_by == owner_instance_id,
        )
        .values(lock_expires_at=now_utc + timedelta(seconds=ttl_seconds))
        .returning(Job.id)
    )
    return result.scalar_one_or_none() is not None
