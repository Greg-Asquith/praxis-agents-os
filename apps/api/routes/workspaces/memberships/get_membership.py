# apps/api/routes/workspaces/memberships/get_membership.py

"""Route for reading a workspace membership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.memberships import get_membership as get_membership_service
from services.workspaces.schemas import WorkspaceMembershipRead

router = APIRouter()


@router.get("/{workspace_id}/memberships/{membership_id}")
async def get_membership(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    membership_id: Annotated[UUID, Path()],
) -> WorkspaceMembershipRead:
    return await get_membership_service(
        db,
        actor=actor,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
