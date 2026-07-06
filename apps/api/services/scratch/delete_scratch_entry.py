# apps/api/services/scratch/delete_scratch_entry.py

"""Delete one scratch entry."""

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.scratch import ScratchEntry
from services.scratch.domain import ScratchScope, validate_scratch_name
from services.scratch.utils import scope_filters


async def delete_scratch_entry(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    scope: ScratchScope,
    name: str,
) -> bool:
    """Hard-delete a scratch entry by scope and name."""
    normalized_name = validate_scratch_name(name)
    result = await db.execute(
        delete(ScratchEntry)
        .where(
            ScratchEntry.workspace_id == workspace_id,
            ScratchEntry.name == normalized_name,
            *scope_filters(scope),
        )
        .returning(ScratchEntry.id)
    )
    return result.scalar_one_or_none() is not None
