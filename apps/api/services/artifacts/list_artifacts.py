# apps/api/services/artifacts/list_artifacts.py

"""List workspace artifacts."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.artifacts import Artifact, ArtifactRevision
from services.artifacts.schemas import ArtifactListResponse
from services.artifacts.utils import artifact_to_summary


async def list_artifacts(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    limit: int,
    offset: int,
    conversation_id: UUID | None = None,
) -> ArtifactListResponse:
    filters = [
        Artifact.workspace_id == workspace_id,
        Artifact.deleted.is_(False),
    ]
    if conversation_id is not None:
        filters.append(Artifact.conversation_id == conversation_id)
    total = int(await db.scalar(select(func.count()).select_from(Artifact).where(*filters)) or 0)
    artifacts = list(
        (
            await db.scalars(
                select(Artifact)
                .where(*filters)
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    artifact_ids = [artifact.id for artifact in artifacts]
    revision_counts: dict[UUID, int] = {}
    if artifact_ids:
        rows = (
            await db.execute(
                select(
                    ArtifactRevision.artifact_id,
                    func.count(ArtifactRevision.id),
                )
                .where(ArtifactRevision.artifact_id.in_(artifact_ids))
                .group_by(ArtifactRevision.artifact_id)
            )
        ).all()
        revision_counts = {artifact_id: int(version_count) for artifact_id, version_count in rows}
    return ArtifactListResponse(
        items=[
            artifact_to_summary(
                artifact,
                version_count=revision_counts.get(artifact.id, 0),
            )
            for artifact in artifacts
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
