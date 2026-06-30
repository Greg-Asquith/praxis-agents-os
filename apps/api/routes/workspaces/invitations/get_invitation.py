# apps/api/routes/workspaces/invitations/get_invitation.py

"""Route for reading a workspace invitation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import get_invitation as get_invitation_service
from services.workspaces.schemas import WorkspaceInvitationRead

router = APIRouter()


@router.get("/{workspace_id}/invitations/{invitation_id}")
async def get_invitation(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    invitation_id: Annotated[UUID, Path()],
) -> WorkspaceInvitationRead:
    return await get_invitation_service(
        db,
        actor=actor,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
    )
