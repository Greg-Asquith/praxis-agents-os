# apps/api/routes/workspaces/memberships/create_membership.py

"""Route for creating a workspace membership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.memberships import create_membership as create_membership_service
from services.workspaces.schemas import WorkspaceMembershipCreateRequest, WorkspaceMembershipRead

router = APIRouter()


@router.post("/{workspace_id}/memberships", status_code=status.HTTP_201_CREATED)
async def create_membership(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    payload: WorkspaceMembershipCreateRequest,
) -> WorkspaceMembershipRead:
    return await create_membership_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
