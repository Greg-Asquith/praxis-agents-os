# apps/api/routes/workspaces/invitations/delete_invitation.py

"""Route for deleting a workspace invitation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import delete_invitation as delete_invitation_service

router = APIRouter()


@router.delete(
    "/{workspace_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_invitation(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    invitation_id: Annotated[UUID, Path()],
) -> None:
    await delete_invitation_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
