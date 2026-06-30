# apps/api/routes/workspaces/invitations/accept_invitation_by_token.py

"""Route for accepting a workspace invitation by token."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import (
    accept_invitation_by_token as accept_invitation_by_token_service,
)
from services.workspaces.schemas import (
    WorkspaceInvitationAcceptRequest,
    WorkspaceInvitationAcceptResponse,
)

router = APIRouter()


@router.post("/invitations/accept")
async def accept_invitation_by_token(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    payload: WorkspaceInvitationAcceptRequest,
) -> WorkspaceInvitationAcceptResponse:
    return await accept_invitation_by_token_service(
        db,
        request=request,
        actor=actor,
        token=payload.token,
    )
