# apps/api/routes/workspaces/invitations/accept_invitation_by_id.py

"""Route for accepting a workspace invitation by ID."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import (
    accept_invitation_by_id as accept_invitation_by_id_service,
)
from services.workspaces.schemas import WorkspaceInvitationAcceptResponse

router = APIRouter()


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation_by_id(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    invitation_id: Annotated[UUID, Path()],
) -> WorkspaceInvitationAcceptResponse:
    return await accept_invitation_by_id_service(
        db,
        request=request,
        actor=actor,
        invitation_id=invitation_id,
    )
