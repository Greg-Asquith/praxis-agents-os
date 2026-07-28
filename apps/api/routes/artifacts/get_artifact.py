# apps/api/routes/artifacts/get_artifact.py

"""Read one active-workspace artifact."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.artifacts import get_artifact as get_artifact_service
from services.artifacts.schemas import ArtifactRead

router = APIRouter()


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactRead:
    workspace, _membership = workspace_context
    return await get_artifact_service(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
    )
