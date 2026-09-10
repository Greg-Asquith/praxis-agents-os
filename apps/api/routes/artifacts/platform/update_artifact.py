# apps/api/routes/artifacts/platform/update_artifact.py

"""Updates a platform Artifact with a reviewed version."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.schemas import PlatformArtifactRead, PlatformArtifactUpdateRequest
from services.artifacts.platform.update_artifact import update_artifact as update_artifact_service

router = APIRouter()


@router.patch("/{artifact_id}")
async def update_artifact(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
    payload: PlatformArtifactUpdateRequest,
) -> PlatformArtifactRead:
    workspace, _membership = workspace_context
    return await update_artifact_service(
        db,
        actor=actor,
        workspace=workspace,
        request=request,
        artifact_id=artifact_id,
        payload=payload,
    )
