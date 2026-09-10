# apps/api/routes/files/platform/publish_file.py

"""Publishes a reviewed platform File revision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRead, PlatformFilePublishRequest
from services.files.platform import publish_file as publish_file_service

router = APIRouter()


@router.post("/{file_id}/publish")
async def publish_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    payload: PlatformFilePublishRequest,
) -> FileRead:
    return await publish_file_service(
        db,
        actor=actor,
        file_id=file_id,
        request=request,
        payload=payload,
    )
