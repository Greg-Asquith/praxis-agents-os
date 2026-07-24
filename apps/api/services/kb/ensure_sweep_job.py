# apps/api/services/kb/ensure_sweep_job.py

"""Ensure the knowledge-base retention sweep is scheduled."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES

KB_SWEEP_DELETED_KIND = "kb.sweep_deleted"


async def ensure_kb_sweep_job(db: AsyncSession) -> Job:
    """Return an in-flight KB sweep or enqueue one immediately."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == KB_SWEEP_DELETED_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=KB_SWEEP_DELETED_KIND,
        content_hash="sweep-kb:ensure",
        run_after=datetime.now(UTC),
    )
