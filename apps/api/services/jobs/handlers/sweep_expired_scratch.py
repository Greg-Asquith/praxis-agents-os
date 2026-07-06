# apps/api/services/jobs/handlers/sweep_expired_scratch.py

"""Retention sweeper for expired agent scratch entries."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.registry import job_handler
from services.scratch import purge_expired_scratch

SWEEP_EXPIRED_SCRATCH_KIND = "scratch.sweep_expired"

logger = logging.getLogger(__name__)


@job_handler(kind=SWEEP_EXPIRED_SCRATCH_KIND, timeout=120.0)
async def sweep_expired_scratch(db: AsyncSession, job: Job) -> None:
    """Hard-delete expired scratch rows and schedule the next sweep."""
    deleted_count = await purge_expired_scratch(db)
    if deleted_count:
        logger.info("Purged expired scratch entries", extra={"count": deleted_count})

    from services.jobs.enqueue_job import enqueue_job

    now = datetime.now(UTC)
    await enqueue_job(
        db,
        kind=SWEEP_EXPIRED_SCRATCH_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-scratch:{job.id}",
        run_after=now + timedelta(seconds=settings.SCRATCH_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_scratch_sweep_job(db: AsyncSession) -> Job:
    """Ensure at least one scratch-retention sweep is pending or running."""
    from services.jobs.enqueue_job import enqueue_job

    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_EXPIRED_SCRATCH_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    return await enqueue_job(
        db,
        kind=SWEEP_EXPIRED_SCRATCH_KIND,
        content_hash="sweep-scratch:ensure",
        run_after=datetime.now(UTC),
    )
