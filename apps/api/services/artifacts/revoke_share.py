# apps/api/services/artifacts/revoke_share.py

"""Revoke one artifact share."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.artifacts import ArtifactShare
from models.user import User
from services.artifacts.utils import get_artifact_row
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def revoke_artifact_share(
    db: AsyncSession,
    *,
    request: Request,
    workspace_id: UUID,
    artifact_id: UUID,
    share_id: UUID,
    actor: User,
) -> None:
    await get_artifact_row(db, workspace_id=workspace_id, artifact_id=artifact_id)
    share = await db.scalar(
        select(ArtifactShare)
        .where(
            ArtifactShare.id == share_id,
            ArtifactShare.workspace_id == workspace_id,
            ArtifactShare.artifact_id == artifact_id,
        )
        .with_for_update()
    )
    if share is None:
        raise NotFoundError("Artifact share not found")
    if share.revoked_at is not None:
        return
    share.revoked_at = datetime.now(UTC)
    share.revoked_by_user_id = actor.id
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace_id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.ARTIFACT_SHARE,
        resource_id=share.id,
        actor=actor,
        details={"artifact_id": str(artifact_id), "token_prefix": share.token_prefix},
    )
