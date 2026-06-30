# apps/api/routes/workspaces/memberships/delete_membership.py

"""Route for deleting a workspace membership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.memberships import delete_membership as delete_membership_service

router = APIRouter()


@router.delete(
    "/{workspace_id}/memberships/{membership_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_membership(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    membership_id: Annotated[UUID, Path()],
) -> None:
    await delete_membership_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
