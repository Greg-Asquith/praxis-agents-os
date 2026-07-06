# apps/api/services/scratch/read_scratch_entry.py

"""Read one scratch entry and refresh its rolling expiry."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scratch import ScratchEntry
from services.scratch.domain import ScratchScope, validate_scratch_name
from services.scratch.utils import scope_filters, scratch_expires_at


async def read_scratch_entry(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    scope: ScratchScope,
    name: str,
) -> ScratchEntry | None:
    """Return one scratch entry, refreshing expiry when found."""
    normalized_name = validate_scratch_name(name)
    now = datetime.now(UTC)
    entry = await db.scalar(
        select(ScratchEntry).where(
            ScratchEntry.workspace_id == workspace_id,
            ScratchEntry.name == normalized_name,
            ScratchEntry.expires_at > now,
            *scope_filters(scope),
        )
    )
    if entry is None:
        return None
    entry.expires_at = scratch_expires_at()
    await db.flush()
    return entry
