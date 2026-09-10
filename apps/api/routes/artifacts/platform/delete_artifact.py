# apps/api/routes/artifacts/platform/delete_artifact.py

"""Deletes a platform Artifact."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.delete_artifact import delete_artifact as delete_artifact_service

router = APIRouter()


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
) -> Response:
    workspace, _membership = workspace_context
    await delete_artifact_service(
        db,
        actor=actor,
        workspace=workspace,
        request=request,
        artifact_id=artifact_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
