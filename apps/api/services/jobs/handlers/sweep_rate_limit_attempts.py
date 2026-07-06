# apps/api/services/jobs/handlers/sweep_rate_limit_attempts.py

"""Retention sweeper for expired rate-limit attempt rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from models.rate_limiting import RateLimitAttempt
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.registry import job_handler

SWEEP_RATE_LIMIT_ATTEMPTS_KIND = "rate_limits.sweep_attempts"


@job_handler(kind=SWEEP_RATE_LIMIT_ATTEMPTS_KIND, timeout=120.0)
async def sweep_rate_limit_attempts(db: AsyncSession, job: Job) -> None:
    """Hard-delete rate-limit attempt rows past the configured retention window."""
    from services.jobs.enqueue_job import enqueue_job

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.RATE_LIMIT_RETENTION_SECONDS)
    await db.execute(delete(RateLimitAttempt).where(RateLimitAttempt.created_at < cutoff))
    await enqueue_job(
        db,
        kind=SWEEP_RATE_LIMIT_ATTEMPTS_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"rate-limit-sweep:{job.id}",
        run_after=now + timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_rate_limit_sweep_job(db: AsyncSession) -> Job:
    """Ensure at least one rate-limit retention sweep is pending or running."""
    from services.jobs.enqueue_job import enqueue_job

    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_RATE_LIMIT_ATTEMPTS_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    return await enqueue_job(
        db,
        kind=SWEEP_RATE_LIMIT_ATTEMPTS_KIND,
        content_hash="rate-limit-sweep:ensure",
        run_after=datetime.now(UTC),
    )
