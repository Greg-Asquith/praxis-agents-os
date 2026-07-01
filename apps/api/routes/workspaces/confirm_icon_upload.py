# apps/api/routes/workspaces/confirm_icon_upload.py

"""Route for confirming a workspace icon upload."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.assets import confirm_workspace_icon_upload
from services.assets.domain import AssetConfirmRequest
from services.workspaces.schemas import WorkspaceRead

router = APIRouter()


@router.post("/{workspace_id}/icon/confirm")
async def confirm_icon_upload(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    payload: AssetConfirmRequest,
) -> WorkspaceRead:
    return await confirm_workspace_icon_upload(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
