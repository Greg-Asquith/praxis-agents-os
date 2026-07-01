# apps/api/routes/workspaces/create_icon_upload.py

"""Route for creating a workspace icon upload grant."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.assets import create_workspace_icon_upload
from services.assets.domain import AssetUploadGrant, AssetUploadRequest

router = APIRouter()


@router.post("/{workspace_id}/icon/upload")
async def create_icon_upload(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    payload: AssetUploadRequest,
) -> AssetUploadGrant:
    return await create_workspace_icon_upload(
        db,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
