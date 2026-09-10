# apps/api/services/artifacts/platform/delete_artifact.py

"""Deletes a platform Artifact under super-admin authority."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.utils import platform_artifact, platform_session, record_change
from services.audit_events.platform_content_events import PlatformContentAuditDetails


async def delete_artifact(
    db: AsyncSession, *, request: Request, actor: User, workspace: Workspace, artifact_id: UUID
) -> None:
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        artifact = await platform_artifact(maintenance_db, artifact_id, lock=True)
        artifact.is_published = False
        artifact.soft_delete(cascade=False)
        await record_change(
            maintenance_db,
            artifact=artifact,
            actor=actor,
            membership=membership,
            request=request,
            details=PlatformContentAuditDetails(
                operation="delete", revision_id=artifact.current_version_id
            ),
        )
