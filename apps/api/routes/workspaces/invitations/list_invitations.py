# apps/api/routes/workspaces/invitations/list_invitations.py

"""Route for listing workspace invitations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces.invitations import list_invitations as list_invitations_service
from services.workspaces.schemas import WorkspaceInvitationsListResponse

router = APIRouter()


@router.get("/{workspace_id}/invitations")
async def list_invitations(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    include_accepted: Annotated[bool, Query()] = False,
    include_expired: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspaceInvitationsListResponse:
    return await list_invitations_service(
        db,
        actor=actor,
        workspace_id=workspace_id,
        include_accepted=include_accepted,
        include_expired=include_expired,
        limit=limit,
        offset=offset,
    )
