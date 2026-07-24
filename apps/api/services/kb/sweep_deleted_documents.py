# apps/api/services/kb/sweep_deleted_documents.py

"""Hard-delete expired knowledge-base tombstones."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.kb import KBDocument

_SWEEP_BATCH_SIZE = 100


async def sweep_deleted_kb_documents(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Delete one bounded batch whose retention window has elapsed."""
    now_utc = now or datetime.now(UTC)
    cutoff = now_utc - timedelta(days=settings.KB_DELETED_RETENTION_DAYS)
    documents = (
        await db.scalars(
            select(KBDocument)
            .where(
                KBDocument.deleted.is_(True),
                KBDocument.deleted_at.is_not(None),
                KBDocument.deleted_at < cutoff,
            )
            .order_by(KBDocument.deleted_at, KBDocument.id)
            .limit(_SWEEP_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for document in documents:
        await db.delete(document)
    return len(documents)
