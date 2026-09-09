# apps/api/services/jobs/handlers/sweep_abandoned_agent_runs.py

"""Recovers abandoned executions through the recurring jobs queue."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.agent_runs.reap_abandoned import reap_abandoned_runs
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.enqueue_job import enqueue_job
from services.jobs.registry import job_handler

SWEEP_ABANDONED_AGENT_RUNS_KIND = "agent_runs.sweep_abandoned"


@job_handler(kind=SWEEP_ABANDONED_AGENT_RUNS_KIND, timeout=120.0)
async def sweep_abandoned_agent_runs(db: AsyncSession, job: Job) -> None:
    """Settles abandoned families and enqueues the next sweep in the same transaction."""
    await reap_abandoned_runs(db)
    await enqueue_job(
        db,
        kind=SWEEP_ABANDONED_AGENT_RUNS_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-abandoned:{job.id}",
        run_after=datetime.now(UTC) + timedelta(seconds=settings.AGENT_RUN_REAPER_INTERVAL_SECONDS),
    )


async def ensure_abandoned_agent_run_sweep_job(db: AsyncSession) -> Job:
    """Ensures an abandoned-run sweep is pending or running."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_ABANDONED_AGENT_RUNS_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing
    return await enqueue_job(
        db,
        kind=SWEEP_ABANDONED_AGENT_RUNS_KIND,
        content_hash="sweep-abandoned:ensure",
        run_after=datetime.now(UTC),
    )
