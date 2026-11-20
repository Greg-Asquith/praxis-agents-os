# apps/api/services/jobs/handlers/memory_dream.py

"""Job adapters for learning from finished conversations (internally, dreaming)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.registry import job_handler
from services.memories.dream import advance_dream_run, fail_dream_run, schedule_dreams
from services.memories.dream.domain import MEMORY_DREAM_JOB_KIND, MEMORY_DREAM_SCHEDULE_JOB_KIND


@job_handler(kind=MEMORY_DREAM_SCHEDULE_JOB_KIND, timeout=120.0)
async def handle_memory_dream_schedule(db: AsyncSession, job: Job) -> None:
    """Start due dreams and schedule the next pass while the feature is on."""
    if not settings.MEMORY_DREAM_ENABLED:
        return
    now = datetime.now(UTC)
    await schedule_dreams(db, now=now)

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=MEMORY_DREAM_SCHEDULE_JOB_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"memory-dream-schedule:{job.id}",
        run_after=now + timedelta(seconds=settings.MEMORY_DREAM_INTERVAL_SECONDS),
    )


@job_handler(
    kind=MEMORY_DREAM_JOB_KIND, timeout=900.0, max_attempts=3, on_final_failure=fail_dream_run
)
async def handle_memory_dream(db: AsyncSession, job: Job) -> None:
    """Advance one workspace's dream run by one step."""
    await advance_dream_run(db, job)
