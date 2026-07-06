# apps/api/services/scratch/list_scratch_entries.py

"""List scratch entries without returning their content."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scratch import ScratchEntry
from services.scratch.domain import ScratchEntrySummary, ScratchScope
from services.scratch.utils import scope_filters


async def list_scratch_entries(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    scope: ScratchScope,
) -> list[ScratchEntrySummary]:
    """Return scratch entry summaries for one scope."""
    now = datetime.now(UTC)
    entries = (
        await db.scalars(
            select(ScratchEntry)
            .where(
                ScratchEntry.workspace_id == workspace_id,
                ScratchEntry.expires_at > now,
                *scope_filters(scope),
            )
            .order_by(ScratchEntry.updated_at.desc(), ScratchEntry.name)
        )
    ).all()
    return [
        ScratchEntrySummary(
            name=entry.name,
            content_bytes=entry.content_bytes,
            updated_at=entry.updated_at,
            expires_at=entry.expires_at,
        )
        for entry in entries
    ]
