# apps/api/services/kb/integration_sources/ensure_reconcile_job.py

"""Ensure periodic Knowledge Base integration-source reconciliation."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES

KB_RECONCILE_INTEGRATION_SOURCES_KIND = "kb.reconcile_integration_sources"


async def ensure_kb_integration_reconcile_job(db: AsyncSession) -> Job:
    """Returns an in-flight integration-source scan or enqueues one immediately."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == KB_RECONCILE_INTEGRATION_SOURCES_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=KB_RECONCILE_INTEGRATION_SOURCES_KIND,
        content_hash="reconcile-kb-sources:ensure",
        run_after=datetime.now(UTC),
    )
