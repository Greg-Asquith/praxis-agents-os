# apps/api/services/kb/ensure_reconcile_job.py

"""Ensure periodic Knowledge Base source reconciliation."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES

KB_RECONCILE_SOURCES_KIND = "kb.reconcile_sources"


async def ensure_kb_reconcile_job(db: AsyncSession) -> Job:
    """Return an in-flight source scan or enqueue one immediately."""
    existing = await db.scalar(
        select(Job).where(
            Job.kind == KB_RECONCILE_SOURCES_KIND,
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    if existing is not None:
        return existing

    from services.jobs.enqueue_job import enqueue_job

    return await enqueue_job(
        db,
        kind=KB_RECONCILE_SOURCES_KIND,
        content_hash="reconcile-kb-sources:ensure",
        run_after=datetime.now(UTC),
    )
