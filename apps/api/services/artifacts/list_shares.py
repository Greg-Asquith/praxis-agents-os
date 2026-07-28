# apps/api/services/artifacts/list_shares.py

"""List unexpired shares for one artifact."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.artifacts import ArtifactShare
from models.user import User
from services.artifacts.schemas import ArtifactShareListResponse, ArtifactShareRead
from services.artifacts.utils import get_artifact_row


async def list_artifact_shares(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    artifact_id: UUID,
) -> ArtifactShareListResponse:
    await get_artifact_row(db, workspace_id=workspace_id, artifact_id=artifact_id)
    rows = (
        await db.execute(
            select(ArtifactShare, User.display_name, User.email)
            .outerjoin(User, User.id == ArtifactShare.created_by_user_id)
            .where(
                ArtifactShare.workspace_id == workspace_id,
                ArtifactShare.artifact_id == artifact_id,
                ArtifactShare.expires_at > datetime.now(UTC),
            )
            .order_by(ArtifactShare.created_at.desc(), ArtifactShare.id.desc())
        )
    ).all()
    return ArtifactShareListResponse(
        items=[
            ArtifactShareRead(
                id=share.id,
                token_prefix=share.token_prefix,
                expires_at=share.expires_at,
                version_id=share.version_id,
                created_at=share.created_at,
                created_by_user_id=share.created_by_user_id,
                creator_display=display_name or email,
                revoked_at=share.revoked_at,
                revoked_by_user_id=share.revoked_by_user_id,
                last_accessed_at=share.last_accessed_at,
                access_count=share.access_count,
            )
            for share, display_name, email in rows
        ]
    )
