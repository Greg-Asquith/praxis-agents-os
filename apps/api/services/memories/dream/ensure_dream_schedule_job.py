# apps/api/services/memories/dream/ensure_dream_schedule_job.py

"""Ensure the dream scheduler is queued while learning from conversations is on."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.memories.dream.domain import MEMORY_DREAM_SCHEDULE_JOB_KIND


async def ensure_dream_schedule_job(db: AsyncSession) -> Job | None:
    """Returns the in-flight scheduler, enqueues one, or returns None while the feature is off."""
    if not settings.MEMORY_DREAM_ENABLED:
        return None
    existing = await db.scalar(
        select(Job).where(
            Job.kind == MEMORY_DREAM_SCHEDULE_JOB_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=MEMORY_DREAM_SCHEDULE_JOB_KIND,
        content_hash="memory-dream-schedule:ensure",
        run_after=datetime.now(UTC),
    )
