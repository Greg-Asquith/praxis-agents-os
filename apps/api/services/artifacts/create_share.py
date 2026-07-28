# apps/api/services/artifacts/create_share.py

"""Create one version-pinned artifact share."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.artifacts import ArtifactShare
from models.user import User
from models.workspace import Workspace
from services.artifacts.utils import check_workspace_share_rate_limit, get_artifact_row
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from utils.security import hash_token


async def create_artifact_share(
    db: AsyncSession,
    *,
    request: Request,
    workspace: Workspace,
    actor: User,
    artifact_id: UUID,
    expires_in_days: int | None = None,
) -> tuple[ArtifactShare, str]:
    if not settings.ARTIFACT_SHARING_ENABLED:
        raise AppValidationError("Artifact sharing is not enabled")

    artifact = await get_artifact_row(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
    )
    if artifact.current_version_id is None:
        raise RuntimeError("Artifact has no current revision")
    await check_workspace_share_rate_limit(db, workspace_id=workspace.id)

    ttl_days = expires_in_days or settings.ARTIFACT_SHARE_DEFAULT_TTL_DAYS
    ttl_days = min(max(ttl_days, 1), settings.ARTIFACT_SHARE_MAX_TTL_DAYS)
    token = secrets.token_urlsafe(32)
    share = ArtifactShare(
        workspace_id=workspace.id,
        artifact_id=artifact.id,
        version_id=artifact.current_version_id,
        token_hash=hash_token(token),
        token_prefix=token[:8],
        expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        created_by_user_id=actor.id,
    )
    db.add(share)
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.ARTIFACT_SHARE,
        resource_id=share.id,
        actor=actor,
        details={
            "artifact_id": str(artifact.id),
            "version_id": str(share.version_id),
            "expires_at": share.expires_at.isoformat(),
            "token_prefix": share.token_prefix,
        },
    )
    return share, token
