# apps/api/routes/workspaces/invitations/update_invitation.py

"""Route for updating a workspace invitation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import update_invitation as update_invitation_service
from services.workspaces.schemas import WorkspaceInvitationRead, WorkspaceInvitationUpdateRequest

router = APIRouter()


@router.patch("/{workspace_id}/invitations/{invitation_id}")
async def update_invitation(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    invitation_id: Annotated[UUID, Path()],
    payload: WorkspaceInvitationUpdateRequest,
) -> WorkspaceInvitationRead:
    return await update_invitation_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
        payload=payload,
    )
