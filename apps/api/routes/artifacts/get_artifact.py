# apps/api/routes/artifacts/get_artifact.py

"""Read one active-workspace artifact."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts import get_artifact as get_artifact_service
from services.artifacts.schemas import ArtifactRead

router = APIRouter()


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactRead:
    workspace, membership = workspace_context
    return await get_artifact_service(
        db,
        workspace_id=workspace.id,
        actor=actor,
        membership=membership,
        artifact_id=artifact_id,
    )
