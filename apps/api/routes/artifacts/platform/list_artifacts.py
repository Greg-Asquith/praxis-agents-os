# apps/api/routes/artifacts/platform/list_artifacts.py

"""Lists platform Artifacts for management."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.list_artifacts import list_artifacts as list_artifacts_service
from services.artifacts.platform.schemas import PlatformArtifactListResponse

router = APIRouter()


@router.get("/")
async def list_artifacts(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlatformArtifactListResponse:
    workspace, _membership = workspace_context
    return await list_artifacts_service(
        db,
        actor=actor,
        workspace=workspace,
        limit=limit,
        offset=offset,
    )
