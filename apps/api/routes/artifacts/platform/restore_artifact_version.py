# apps/api/routes/artifacts/platform/restore_artifact_version.py

"""Restores a platform Artifact version."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.restore_artifact_version import (
    restore_artifact_version as restore_artifact_version_service,
)
from services.artifacts.platform.schemas import PlatformArtifactRead, PlatformArtifactRestoreRequest

router = APIRouter()


@router.post("/{artifact_id}/restore")
async def restore_artifact_version(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
    payload: PlatformArtifactRestoreRequest,
) -> PlatformArtifactRead:
    workspace, _membership = workspace_context
    return await restore_artifact_version_service(
        db,
        actor=actor,
        workspace=workspace,
        request=request,
        artifact_id=artifact_id,
        payload=payload,
    )
