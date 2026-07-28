# apps/api/routes/artifacts/create_share.py

"""Create an anonymous artifact share."""

from typing import Annotated
from urllib.parse import urljoin
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_owner,
)
from core.settings import settings
from services.artifacts import create_artifact_share
from services.artifacts.schemas import ArtifactShareCreated, ArtifactShareCreateRequest

router = APIRouter(dependencies=[Depends(require_owner)])


@router.post("/{artifact_id}/shares", status_code=status.HTTP_201_CREATED)
async def create_share(
    request: Request,
    payload: ArtifactShareCreateRequest,
    artifact_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactShareCreated:
    workspace, _membership = workspace_context
    share, token = await create_artifact_share(
        db,
        request=request,
        workspace=workspace,
        actor=actor,
        artifact_id=artifact_id,
        expires_in_days=payload.expires_in_days,
    )
    origin = settings.ARTIFACT_ORIGIN or settings.APP_BASE_URL
    return ArtifactShareCreated(
        id=share.id,
        share_url=urljoin(f"{origin.rstrip('/')}/", f"artifacts/shared/{token}"),
        token_prefix=share.token_prefix,
        expires_at=share.expires_at,
        version_id=share.version_id,
    )
