# apps/api/routes/workspaces/memberships/update_membership.py

"""Route for updating a workspace membership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.memberships import update_membership as update_membership_service
from services.workspaces.schemas import WorkspaceMembershipRead, WorkspaceMembershipUpdateRequest

router = APIRouter()


@router.patch("/{workspace_id}/memberships/{membership_id}")
async def update_membership(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    membership_id: Annotated[UUID, Path()],
    payload: WorkspaceMembershipUpdateRequest,
) -> WorkspaceMembershipRead:
    return await update_membership_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        membership_id=membership_id,
        payload=payload,
    )
