# apps/api/services/kb/integration_sources/reconcile.py

"""Queue refreshes for due Knowledge Base integration sources."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.kb import KBDocument
from services.kb.domain import (
    KB_SOURCE_INTEGRATION,
    KB_SYNC_ERROR,
    KB_SYNC_READY,
    KB_SYNC_UNAVAILABLE,
)

_RECONCILABLE_SYNC_STATUSES = (KB_SYNC_READY, KB_SYNC_ERROR, KB_SYNC_UNAVAILABLE)


async def reconcile_kb_integration_sources(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Enqueues one bounded batch of due integration-source refreshes."""
    now_utc = now or datetime.now(UTC)
    cutoff = now_utc - timedelta(seconds=settings.KB_INTEGRATION_SOURCE_REFRESH_INTERVAL_SECONDS)
    rows = (
        await db.execute(
            select(KBDocument.id, KBDocument.workspace_id)
            .where(
                KBDocument.source_type == KB_SOURCE_INTEGRATION,
                KBDocument.deleted.is_(False),
                KBDocument.source_sync_status.in_(_RECONCILABLE_SYNC_STATUSES),
                or_(
                    KBDocument.source_synced_at.is_(None),
                    KBDocument.source_synced_at < cutoff,
                ),
            )
            .order_by(KBDocument.source_synced_at.nulls_first(), KBDocument.id)
            .limit(settings.KB_INTEGRATION_SOURCE_SCAN_BATCH_SIZE)
        )
    ).all()

    from services.jobs.enqueue_job import enqueue_job

    for document_id, workspace_id in rows:
        await enqueue_job(
            db,
            kind="kb.ingest_document",
            workspace_id=workspace_id,
            subject_type="kb_document",
            subject_id=document_id,
            initiated_by_user_id=None,
        )
    return len(rows)
