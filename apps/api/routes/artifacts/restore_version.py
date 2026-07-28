# apps/api/routes/artifacts/restore_version.py

"""Restore an artifact version by appending a revision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.artifacts import get_artifact, restore_artifact_version
from services.artifacts.schemas import ArtifactRead

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/{artifact_id}/versions/{version_id}/restore")
async def restore_version(
    artifact_id: Annotated[UUID, Path()],
    version_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactRead:
    workspace, _membership = workspace_context
    await restore_artifact_version(
        db,
        workspace=workspace,
        artifact_id=artifact_id,
        version_id=version_id,
        actor=actor,
    )
    return await get_artifact(db, workspace_id=workspace.id, artifact_id=artifact_id)
