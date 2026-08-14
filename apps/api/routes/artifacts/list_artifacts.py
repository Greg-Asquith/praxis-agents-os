# apps/api/routes/artifacts/list_artifacts.py

"""List artifacts visible in the active workspace."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.artifacts import list_artifacts as list_artifacts_service
from services.artifacts.schemas import ArtifactListResponse

router = APIRouter()


@router.get("/")
async def list_artifacts(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    conversation_id: Annotated[UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=255)] = None,
    sort_by: Annotated[str, Query(max_length=32)] = "updated_at",
    sort_direction: Annotated[str, Query(max_length=4)] = "desc",
) -> ArtifactListResponse:
    workspace, _membership = workspace_context
    return await list_artifacts_service(
        db,
        workspace_id=workspace.id,
        limit=limit,
        offset=offset,
        conversation_id=conversation_id,
        search=search,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
