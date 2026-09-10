# apps/api/routes/files/platform/get_file_content.py

"""Route for authenticated platform file text content."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRevisionContentRead
from services.files.platform import get_file_content as get_file_content_service

router = APIRouter()


@router.get("/{file_id}/content")
async def get_file_content(
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    revision_id: Annotated[UUID | None, Query()] = None,
) -> FileRevisionContentRead:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return await get_file_content_service(db, actor=actor, file_id=file_id, revision_id=revision_id)
