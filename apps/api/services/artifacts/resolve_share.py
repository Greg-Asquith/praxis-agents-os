# apps/api/services/artifacts/resolve_share.py

"""Resolve and account for one anonymous artifact share."""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.artifacts import Artifact, ArtifactShare
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
)
from services.audit_events.operations import safe_record_operation_audit_event
from utils.security import hash_token


async def resolve_artifact_share(
    db: AsyncSession,
    *,
    token: str,
    request: Request,
) -> tuple[ArtifactShare, Artifact]:
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(ArtifactShare, Artifact)
            .join(Artifact, Artifact.id == ArtifactShare.artifact_id)
            .where(
                ArtifactShare.token_hash == hash_token(token),
                ArtifactShare.revoked_at.is_(None),
                ArtifactShare.expires_at > now,
                Artifact.deleted.is_(False),
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Share not found")
    share, artifact = row

    audit_cutoff = now - timedelta(hours=1)
    accounted_at = await db.scalar(
        update(ArtifactShare)
        .where(ArtifactShare.id == share.id)
        .values(
            access_count=ArtifactShare.access_count + 1,
            last_accessed_at=case(
                (
                    (ArtifactShare.last_accessed_at.is_(None))
                    | (ArtifactShare.last_accessed_at < audit_cutoff),
                    now,
                ),
                else_=ArtifactShare.last_accessed_at,
            ),
        )
        .returning(ArtifactShare.last_accessed_at)
    )
    if accounted_at == now:
        await safe_record_operation_audit_event(
            db,
            workspace_id=share.workspace_id,
            action=AuditAction.READ,
            resource_type=AuditResourceType.ARTIFACT_SHARE,
            resource_id=share.id,
            actor_type=AuditActorType.SYSTEM,
            actor_display="anonymous",
            details={"artifact_id": str(artifact.id)},
            request=request,
        )
    await db.refresh(share)
    return share, artifact
