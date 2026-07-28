# apps/api/routes/artifacts/list_shares.py

"""List artifact shares."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep, require_owner
from services.artifacts import list_artifact_shares
from services.artifacts.schemas import ArtifactShareListResponse

router = APIRouter(dependencies=[Depends(require_owner)])


@router.get("/{artifact_id}/shares")
async def list_shares(
    artifact_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactShareListResponse:
    workspace, _membership = workspace_context
    return await list_artifact_shares(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
    )
