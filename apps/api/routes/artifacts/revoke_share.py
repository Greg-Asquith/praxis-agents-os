# apps/api/routes/artifacts/revoke_share.py

"""Revoke an artifact share."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_owner,
)
from services.artifacts import revoke_artifact_share

router = APIRouter(dependencies=[Depends(require_owner)])


@router.delete("/{artifact_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    request: Request,
    artifact_id: Annotated[UUID, Path()],
    share_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> Response:
    workspace, _membership = workspace_context
    await revoke_artifact_share(
        db,
        request=request,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
        share_id=share_id,
        actor=actor,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
