# apps/api/services/memories/dream/fail_dream_run.py

"""Fail a dream run whose job failed for good, so the next dream can start."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from models.memory_dream_run import MemoryDreamRun
from services.memories.dream.domain import (
    DREAM_ERROR_JOB_FAILED,
    DREAM_STATUS_FAILED,
    FINAL_DREAM_STATUSES,
)
from services.memories.dream.utils import move_dream_run


async def fail_dream_run(db: AsyncSession, job: Job) -> None:
    """Moves the job's run to failed; its window is read again by the next dream."""
    run = await db.scalar(
        select(MemoryDreamRun).where(MemoryDreamRun.id == job.subject_id).with_for_update()
    )
    if run is None or run.status in FINAL_DREAM_STATUSES:
        return
    move_dream_run(
        run, DREAM_STATUS_FAILED, now=datetime.now(UTC), error_code=DREAM_ERROR_JOB_FAILED
    )
    await db.flush()
