# apps/api/routes/artifacts/copy_artifact.py

"""Copies one published platform version into the active workspace."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.artifacts.copy_artifact import copy_artifact as copy_artifact_service
from services.artifacts.schemas import ArtifactCopyRequest, ArtifactRead

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/{artifact_id}/copy")
async def copy_artifact(
    artifact_id: UUID,
    payload: ArtifactCopyRequest,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactRead:
    workspace, _membership = workspace_context
    return await copy_artifact_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        artifact_id=artifact_id,
        payload=payload,
    )
