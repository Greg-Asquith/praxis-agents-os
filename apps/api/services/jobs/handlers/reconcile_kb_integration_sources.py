# apps/api/services/jobs/handlers/reconcile_kb_integration_sources.py

"""Job adapter for Knowledge Base integration-source reconciliation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.integration_sources.ensure_reconcile_job import (
    KB_RECONCILE_INTEGRATION_SOURCES_KIND,
)
from services.kb.integration_sources.reconcile import reconcile_kb_integration_sources


@job_handler(kind=KB_RECONCILE_INTEGRATION_SOURCES_KIND, timeout=120.0)
async def handle_reconcile_kb_integration_sources(db: AsyncSession, job: Job) -> None:
    """Queues due source refreshes and schedules the next scan."""
    now = datetime.now(UTC)
    await reconcile_kb_integration_sources(db, now=now)

    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=KB_RECONCILE_INTEGRATION_SOURCES_KIND,
        payload={"scheduled_by_job_id": str(job.id)},
        content_hash=f"reconcile-kb-sources:{job.id}",
        run_after=now + timedelta(seconds=settings.KB_INTEGRATION_SOURCE_REFRESH_INTERVAL_SECONDS),
    )
