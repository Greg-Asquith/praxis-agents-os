# apps/api/routes/artifacts/create_view_url.py

"""Mint a short-lived view URL for one artifact version."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.artifacts import create_artifact_view_url
from services.artifacts.schemas import ArtifactViewUrl
from services.artifacts.utils import get_artifact_revision, get_artifact_row

router = APIRouter()


@router.get("/{artifact_id}/versions/{version_id}/view-url")
async def create_view_url(
    artifact_id: Annotated[UUID, Path()],
    version_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactViewUrl:
    workspace, _membership = workspace_context
    artifact = await get_artifact_row(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
    )
    await get_artifact_revision(db, artifact=artifact, version_id=version_id)
    return create_artifact_view_url(artifact=artifact, version_id=version_id)
