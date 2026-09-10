# apps/api/routes/artifacts/platform/create_artifact.py

"""Publishes a reviewed workspace Artifact as a platform Artifact."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.create_artifact import create_artifact as create_artifact_service
from services.artifacts.platform.schemas import PlatformArtifactCreateRequest, PlatformArtifactRead

router = APIRouter()


@router.post("/from-workspace/{artifact_id}", status_code=201)
async def create_artifact(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
    payload: PlatformArtifactCreateRequest,
) -> PlatformArtifactRead:
    workspace, _membership = workspace_context
    return await create_artifact_service(
        db,
        actor=actor,
        workspace=workspace,
        request=request,
        artifact_id=artifact_id,
        payload=payload,
    )
