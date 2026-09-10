# apps/api/services/artifacts/platform/restore_artifact_version.py

"""Saves a platform version with optimistic concurrency and live editor authority."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import is_super_admin_email
from core.exceptions.general import NotFoundError
from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import PlatformArtifactRead, PlatformArtifactRestoreRequest
from services.artifacts.platform.utils import (
    append_revision,
    platform_artifact,
    platform_revision,
    platform_session,
    read_content,
    require_editor,
    require_expected,
    reserve_revision,
)


async def restore_artifact_version(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    payload: PlatformArtifactRestoreRequest,
) -> PlatformArtifactRead:
    reservation = await reserve_revision(
        db,
        actor=actor,
        workspace=workspace,
        artifact_id=artifact_id,
        expected_current_version_id=payload.expected_current_version_id,
    )
    async with platform_session(
        db, actor=actor, workspace=workspace, artifact_id=artifact_id, editing=True
    ) as (maintenance_db, actor, membership):
        artifact = await platform_artifact(maintenance_db, artifact_id, lock=True)
        require_editor(artifact, actor=actor, membership=membership)
        require_expected(artifact, payload.expected_current_version_id)
        source = await platform_revision(maintenance_db, artifact, payload.version_id)
        if not is_super_admin_email(actor.email) and not source.is_published:
            raise NotFoundError("Artifact version not found", resource_type="artifact")
        content = (await read_content(artifact, source)).decode("utf-8")
        return await append_revision(
            maintenance_db,
            artifact=artifact,
            actor=actor,
            membership=membership,
            request=request,
            content=content,
            title=artifact.title,
            reservation=reservation,
            restored_from=source,
        )
