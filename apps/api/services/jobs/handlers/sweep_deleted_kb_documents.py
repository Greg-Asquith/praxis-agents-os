# apps/api/services/jobs/handlers/sweep_deleted_kb_documents.py

"""Job adapter for knowledge-base retention."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.ensure_sweep_job import KB_SWEEP_DELETED_KIND
from services.kb.sweep_deleted_documents import sweep_deleted_kb_documents


@job_handler(kind=KB_SWEEP_DELETED_KIND, timeout=120.0)
async def handle_sweep_deleted_kb_documents(db: AsyncSession, job: Job) -> None:
    """Sweep expired documents and schedule the next pass."""
    now = datetime.now(UTC)
    await sweep_deleted_kb_documents(db, now=now)
    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=KB_SWEEP_DELETED_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"sweep-kb:{job.id}",
        run_after=now + timedelta(seconds=settings.KB_SWEEP_INTERVAL_SECONDS),
    )
