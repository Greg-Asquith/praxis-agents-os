# apps/api/routes/workspaces/memberships/list_memberships.py

"""Route for listing workspace memberships."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.memberships import list_memberships as list_memberships_service
from services.workspaces.schemas import WorkspaceMembershipsListResponse

router = APIRouter()


@router.get("/{workspace_id}/memberships")
async def list_memberships(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspaceMembershipsListResponse:
    return await list_memberships_service(
        db,
        actor=actor,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
    )
