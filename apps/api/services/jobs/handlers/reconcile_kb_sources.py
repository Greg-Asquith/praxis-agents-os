# apps/api/services/jobs/handlers/reconcile_kb_sources.py

"""Job adapter for Knowledge Base source reconciliation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.ensure_reconcile_job import KB_RECONCILE_SOURCES_KIND
from services.kb.reconcile_sources import reconcile_kb_sources


@job_handler(kind=KB_RECONCILE_SOURCES_KIND, timeout=120.0)
async def handle_reconcile_kb_sources(db: AsyncSession, job: Job) -> None:
    """Queue due source refreshes and schedule the next scan."""
    now = datetime.now(UTC)
    await reconcile_kb_sources(db, now=now)

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=KB_RECONCILE_SOURCES_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"reconcile-kb-sources:{job.id}",
        run_after=now + timedelta(seconds=settings.KB_SOURCE_REFRESH_INTERVAL_SECONDS),
    )
