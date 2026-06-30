# apps/api/routes/workspaces/invitations/create_invitation.py

"""Route for creating a workspace invitation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import create_invitation as create_invitation_service
from services.workspaces.schemas import (
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationCreateResponse,
)

router = APIRouter()


@router.post("/{workspace_id}/invitations", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    payload: WorkspaceInvitationCreateRequest,
) -> WorkspaceInvitationCreateResponse:
    return await create_invitation_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
