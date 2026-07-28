# apps/api/routes/artifacts/update_artifact.py

"""Edit an artifact by appending a revision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.artifacts import get_artifact, update_artifact as update_artifact_service
from services.artifacts.schemas import ArtifactRead, ArtifactUpdateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.patch("/{artifact_id}")
async def update_artifact(
    payload: ArtifactUpdateRequest,
    artifact_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactRead:
    workspace, _membership = workspace_context
    await update_artifact_service(
        db,
        workspace=workspace,
        artifact_id=artifact_id,
        content=payload.content,
        title=payload.title,
        actor_user_id=actor.id,
    )
    return await get_artifact(db, workspace_id=workspace.id, artifact_id=artifact_id)
