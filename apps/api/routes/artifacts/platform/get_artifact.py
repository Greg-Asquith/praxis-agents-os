# apps/api/routes/artifacts/platform/get_artifact.py

"""Returns a platform Artifact for management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.get_artifact import get_artifact as get_artifact_service
from services.artifacts.platform.schemas import PlatformArtifactRead

router = APIRouter()


@router.get("/{artifact_id}")
async def get_artifact(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
) -> PlatformArtifactRead:
    workspace, _membership = workspace_context
    return await get_artifact_service(
        db,
        actor=actor,
        workspace=workspace,
        artifact_id=artifact_id,
    )
