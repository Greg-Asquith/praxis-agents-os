# apps/api/services/jobs/handlers/sweep_terminal_jobs.py

"""Retention sweeper for terminal generic job rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES, TERMINAL_JOB_STATUSES
from services.jobs.registry import job_handler

SWEEP_TERMINAL_JOBS_KIND = "jobs.sweep_terminal"


@job_handler(kind=SWEEP_TERMINAL_JOBS_KIND, timeout=120.0)
async def sweep_terminal_jobs(db: AsyncSession, job: Job) -> None:
    """Hard-delete terminal job rows past the configured retention window."""
    from services.jobs.enqueue_job import enqueue_job

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=settings.JOBS_TERMINAL_RETENTION_DAYS)
    await db.execute(
        delete(Job).where(
            Job.status.in_(TERMINAL_JOB_STATUSES),
            Job.finished_at.is_not(None),
            Job.finished_at < cutoff,
        )
    )
    await enqueue_job(
        db,
        kind=SWEEP_TERMINAL_JOBS_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-terminal:{job.id}",
        run_after=now + timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_sweep_job(db: AsyncSession) -> Job:
    """Ensure at least one terminal-job sweep is pending or running."""
    from services.jobs.enqueue_job import enqueue_job

    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_TERMINAL_JOBS_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    return await enqueue_job(
        db,
        kind=SWEEP_TERMINAL_JOBS_KIND,
        content_hash="sweep-terminal:ensure",
        run_after=datetime.now(UTC),
    )
