# apps/api/services/artifacts/platform/publish_artifact.py

"""Publishes the reviewed current version with strict audit evidence."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import PlatformArtifactRead, PlatformArtifactVersionRequest
from services.artifacts.platform.utils import (
    platform_artifact,
    platform_revision,
    platform_session,
    publish_revision,
    record_change,
    require_expected,
    to_read,
)
from services.audit_events.platform_content_events import PlatformContentAuditDetails


async def publish_artifact(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    payload: PlatformArtifactVersionRequest,
) -> PlatformArtifactRead:
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        artifact = await platform_artifact(maintenance_db, artifact_id, lock=True)
        require_expected(artifact, payload.expected_current_version_id)
        revision = await platform_revision(maintenance_db, artifact, artifact.current_version_id)
        previous = artifact.published_version_id
        await publish_revision(maintenance_db, artifact, revision)
        await record_change(
            maintenance_db,
            artifact=artifact,
            actor=actor,
            membership=membership,
            request=request,
            details=PlatformContentAuditDetails(
                operation="publish", revision_id=revision.id, previous_revision_id=previous
            ),
        )
        return await to_read(maintenance_db, artifact, actor, membership)
