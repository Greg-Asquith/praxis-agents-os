# apps/api/routes/artifacts/platform/get_version_content.py

"""Returns platform Artifact version content for review."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.get_version_content import (
    get_version_content as get_version_content_service,
)
from services.artifacts.schemas import ArtifactVersionContentRead

router = APIRouter()


@router.get("/{artifact_id}/content")
async def get_version_content(
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
    version_id: Annotated[UUID | None, Query()] = None,
) -> ArtifactVersionContentRead:
    response.headers["Cache-Control"] = "private, no-store"
    workspace, _membership = workspace_context
    return await get_version_content_service(
        db,
        actor=actor,
        workspace=workspace,
        artifact_id=artifact_id,
        version_id=version_id,
    )
