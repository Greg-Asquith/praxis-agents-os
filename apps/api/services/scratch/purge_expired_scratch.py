# apps/api/services/scratch/purge_expired_scratch.py

"""Purge expired scratch entries."""

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.scratch import ScratchEntry


async def purge_expired_scratch(db: AsyncSession) -> int:
    """Hard-delete scratch entries whose rolling TTL has expired."""
    result = await db.execute(
        delete(ScratchEntry)
        .where(ScratchEntry.expires_at < datetime.now(UTC))
        .returning(ScratchEntry.id)
    )
    return len(result.scalars().all())
