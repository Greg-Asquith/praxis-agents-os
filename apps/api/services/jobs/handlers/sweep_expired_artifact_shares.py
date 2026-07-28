# apps/api/services/jobs/handlers/sweep_expired_artifact_shares.py

"""Retention sweeper for expired artifact shares."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.artifacts import ArtifactShare
from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.jobs.registry import job_handler

SWEEP_EXPIRED_ARTIFACT_SHARES_KIND = "artifacts.sweep_expired_shares"


@job_handler(kind=SWEEP_EXPIRED_ARTIFACT_SHARES_KIND, timeout=120.0)
async def sweep_expired_artifact_shares(db: AsyncSession, job: Job) -> None:
    now = datetime.now(UTC)
    await db.execute(delete(ArtifactShare).where(ArtifactShare.expires_at < now))

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=SWEEP_EXPIRED_ARTIFACT_SHARES_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-artifact-shares:{job.id}",
        run_after=now + timedelta(seconds=settings.JOBS_SWEEP_INTERVAL_SECONDS),
    )


async def ensure_artifact_shares_sweep_job(db: AsyncSession) -> Job:
    existing = await db.scalar(
        select(Job).where(
            Job.kind == SWEEP_EXPIRED_ARTIFACT_SHARES_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=SWEEP_EXPIRED_ARTIFACT_SHARES_KIND,
        content_hash="sweep-artifact-shares:ensure",
        run_after=datetime.now(UTC),
    )
