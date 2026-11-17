# apps/api/services/media/media_generations.py

"""The paid generation record each media tool call commits around its provider call."""

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from models.media_generation import MediaGeneration


async def find_media_generation(
    db: AsyncSession, *, workspace_id: UUID, run_id: UUID, tool_call_id: str
) -> MediaGeneration | None:
    """Returns the record a tool call already wrote, if any."""
    return await db.scalar(
        select(MediaGeneration).where(
            MediaGeneration.workspace_id == workspace_id,
            MediaGeneration.run_id == run_id,
            MediaGeneration.tool_call_id == tool_call_id,
        )
    )


async def settle_media_generation(
    db: AsyncSession,
    record: MediaGeneration,
    status: Literal["running", "saved", "failed"],
    *,
    external_id: str | None = None,
    revision: FileRevision | None = None,
    error: str | None = None,
) -> None:
    """Moves the record on and commits, so the state outlives a stopped worker."""
    record.status = status
    if external_id is not None:
        record.external_id = external_id
    if revision is not None:
        record.file_id = revision.file_id
        record.revision_id = revision.id
    if error is not None:
        record.error = error[:500]
    await db.commit()
