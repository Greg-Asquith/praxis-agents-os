# apps/api/routes/artifacts/platform/withdraw_artifact.py

"""Withdraws a platform Artifact."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.artifacts.platform.schemas import PlatformArtifactRead
from services.artifacts.platform.withdraw_artifact import (
    withdraw_artifact as withdraw_artifact_service,
)

router = APIRouter()


@router.post("/{artifact_id}/withdraw")
async def withdraw_artifact(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    artifact_id: Annotated[UUID, Path()],
) -> PlatformArtifactRead:
    workspace, _membership = workspace_context
    return await withdraw_artifact_service(
        db,
        actor=actor,
        workspace=workspace,
        request=request,
        artifact_id=artifact_id,
    )
