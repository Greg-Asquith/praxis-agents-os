# apps/api/services/memories/ensure_sweetp_job.py

"""Ensure the agent-memory retention sweep is scheduled."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES

MEMORY_SWEEP_EXPIRED_JOB_KIND = "memory.sweep_expired"


async def ensure_memory_sweep_job(db: AsyncSession) -> Job:
    """Return an in-flight memory sweep or enqueue one immediately."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == MEMORY_SWEEP_EXPIRED_JOB_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=MEMORY_SWEEP_EXPIRED_JOB_KIND,
        content_hash="sweep-memory:ensure",
        run_after=datetime.now(UTC),
    )
