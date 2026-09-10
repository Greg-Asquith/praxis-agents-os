# apps/api/services/artifacts/platform/withdraw_artifact.py

"""Withdraws a platform Artifact under super-admin authority."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import PlatformArtifactRead
from services.artifacts.platform.utils import (
    platform_artifact,
    platform_session,
    record_change,
    to_read,
)
from services.audit_events.platform_content_events import PlatformContentAuditDetails


async def withdraw_artifact(
    db: AsyncSession, *, request: Request, actor: User, workspace: Workspace, artifact_id: UUID
) -> PlatformArtifactRead:
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        artifact = await platform_artifact(maintenance_db, artifact_id, lock=True)
        if artifact.published_version_id is None:
            raise AppValidationError(
                "This Artifact has not been published. Delete it to cancel publication."
            )
        artifact.is_published = False
        await record_change(
            maintenance_db,
            artifact=artifact,
            actor=actor,
            membership=membership,
            request=request,
            details=PlatformContentAuditDetails(
                operation="withdraw", revision_id=artifact.current_version_id
            ),
        )
        return await to_read(maintenance_db, artifact, actor, membership)
