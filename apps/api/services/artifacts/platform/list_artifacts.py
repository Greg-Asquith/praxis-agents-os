# apps/api/services/artifacts/platform/list_artifacts.py

"""Lists bounded platform drafts and publications for super-admin review."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.artifacts import Artifact, ArtifactRevision
from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import (
    PlatformArtifactListResponse,
    PlatformArtifactSummaryRead,
)
from services.artifacts.platform.utils import platform_session
from services.artifacts.utils import artifact_to_summary
from utils.pagination import paginate


async def list_artifacts(
    db: AsyncSession, *, actor: User, workspace: Workspace, offset: int = 0, limit: int = 50
) -> PlatformArtifactListResponse:
    if offset < 0 or not 1 <= limit <= 100:
        raise AppValidationError("Invalid pagination")
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        version_count = (
            select(func.count(ArtifactRevision.id))
            .where(
                ArtifactRevision.artifact_id == Artifact.id,
                ArtifactRevision.scope == "platform",
                ArtifactRevision.workspace_id.is_(None),
            )
            .correlate(Artifact)
            .scalar_subquery()
        )
        rows, total = await paginate(
            maintenance_db,
            select(Artifact, version_count).where(
                Artifact.scope == "platform",
                Artifact.workspace_id.is_(None),
                Artifact.deleted.is_(False),
            ),
            Artifact.created_at.desc(),
            Artifact.id,
            limit=limit,
            offset=offset,
            scalars=False,
        )
        return PlatformArtifactListResponse(
            items=[
                PlatformArtifactSummaryRead(
                    **artifact_to_summary(
                        artifact, version_count=count, actor=actor, membership=membership
                    ).model_dump(),
                    published_version_id=artifact.published_version_id,
                )
                for artifact, count in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
