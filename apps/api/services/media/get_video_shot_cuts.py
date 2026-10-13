# apps/api/services/media/get_video_shot_cuts.py

"""Loads a video revision's shot cut times, measuring them once on first need."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from services.media.domain import (
    INVALID_RESPONSE_MESSAGE,
    MediaRendererError,
    SceneCutsOperation,
    SceneCutsResult,
)
from services.media.run_media_operation import run_media_operation


async def get_video_shot_cuts(db: AsyncSession, *, revision: FileRevision) -> tuple[int, ...]:
    """Returns the revision's shot cuts in milliseconds; the caller must have authorised it."""
    if revision.shot_cuts_ms is not None:
        return tuple(revision.shot_cuts_ms)
    operation = await run_media_operation(
        workspace_id=revision.workspace_id, sources=[revision], operation=SceneCutsOperation()
    )
    if not isinstance(operation.result, SceneCutsResult):
        raise MediaRendererError("invalid_response", INVALID_RESPONSE_MESSAGE)
    revision.shot_cuts_ms = list(operation.result.cuts_ms)
    await db.flush()
    return operation.result.cuts_ms
