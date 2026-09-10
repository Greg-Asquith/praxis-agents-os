# apps/api/routes/files/platform/get_file_preview.py

"""Route for authenticated platform file previews."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.platform import get_file_preview as get_file_preview_service

router = APIRouter()


@router.get("/{file_id}/preview")
async def get_file_preview(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    revision_id: Annotated[UUID | None, Query()] = None,
) -> Response:
    content, content_type = await get_file_preview_service(
        db, actor=actor, file_id=file_id, revision_id=revision_id
    )
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
