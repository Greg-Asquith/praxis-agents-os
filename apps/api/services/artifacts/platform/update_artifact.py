# apps/api/services/artifacts/platform/update_artifact.py

"""Saves a platform version with optimistic concurrency and live editor authority."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import PlatformArtifactRead, PlatformArtifactUpdateRequest
from services.artifacts.platform.utils import (
    append_revision,
    platform_artifact,
    platform_session,
    require_editor,
    require_expected,
    reserve_revision,
)


async def update_artifact(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    payload: PlatformArtifactUpdateRequest,
    published_only: bool = False,
) -> PlatformArtifactRead:
    reservation = await reserve_revision(
        db,
        actor=actor,
        workspace=workspace,
        artifact_id=artifact_id,
        expected_current_version_id=payload.expected_current_version_id,
        published_only=published_only,
    )
    async with platform_session(
        db, actor=actor, workspace=workspace, artifact_id=artifact_id, editing=True
    ) as (maintenance_db, actor, membership):
        artifact = await platform_artifact(
            maintenance_db, artifact_id, lock=True, published_only=published_only
        )
        require_editor(artifact, actor=actor, membership=membership, runtime=published_only)
        require_expected(artifact, payload.expected_current_version_id)
        title = payload.title if payload.title is not None else artifact.title
        return await append_revision(
            maintenance_db,
            artifact=artifact,
            actor=actor,
            membership=membership,
            request=request,
            content=payload.content,
            title=title,
            reservation=reservation,
        )
