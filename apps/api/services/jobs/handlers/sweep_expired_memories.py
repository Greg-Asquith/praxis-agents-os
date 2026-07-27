"""Job adapter for agent-memory retention."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.registry import job_handler
from services.memories.ensure_sweep_job import MEMORY_SWEEP_EXPIRED_JOB_KIND
from services.memories.sweep_expired_memories import sweep_expired_memories


@job_handler(kind=MEMORY_SWEEP_EXPIRED_JOB_KIND, timeout=120.0)
async def handle_sweep_expired_memories(db: AsyncSession, job: Job) -> None:
    """Sweep expired memories and schedule the next pass."""
    now = datetime.now(UTC)
    await sweep_expired_memories(db, now=now)

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=MEMORY_SWEEP_EXPIRED_JOB_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-memory:{job.id}",
        run_after=now + timedelta(seconds=settings.MEMORY_SWEEP_INTERVAL_SECONDS),
    )
