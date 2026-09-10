# apps/api/routes/artifacts/platform/publish_artifact.py

"""Publishes a reviewed platform Artifact version."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.publish_artifact import (
    publish_artifact as publish_artifact_service,
)
from services.artifacts.platform.schemas import PlatformArtifactRead, PlatformArtifactVersionRequest

router = APIRouter()


@router.post("/{artifact_id}/publish")
async def publish_artifact(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
    payload: PlatformArtifactVersionRequest,
) -> PlatformArtifactRead:
    workspace, _membership = workspace_context
    return await publish_artifact_service(
        db,
        actor=actor,
        workspace=workspace,
        request=request,
        artifact_id=artifact_id,
        payload=payload,
    )
