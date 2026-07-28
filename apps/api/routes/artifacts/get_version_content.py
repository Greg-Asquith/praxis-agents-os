# apps/api/routes/artifacts/get_version_content.py

"""Read one artifact version's content."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.artifacts import get_version_content as get_version_content_service
from services.artifacts.schemas import ArtifactVersionContentRead
from services.artifacts.utils import get_artifact_row

router = APIRouter()


@router.get("/{artifact_id}/versions/{version_id}/content")
async def get_version_content(
    artifact_id: Annotated[UUID, Path()],
    version_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> ArtifactVersionContentRead:
    workspace, _membership = workspace_context
    artifact = await get_artifact_row(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
    )
    return await get_version_content_service(db, artifact=artifact, version_id=version_id)
