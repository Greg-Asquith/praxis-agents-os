# apps/api/services/artifacts/get_artifact.py

"""Reads one visible Artifact and its published or workspace versions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.artifacts import ArtifactRevision
from models.user import User
from models.workspace import WorkspaceMembership
from services.artifacts.schemas import ArtifactRead
from services.artifacts.utils import artifact_to_read, get_artifact_row
from services.artifacts.visibility import visible_artifact_revision_filter


async def get_artifact(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    artifact_id: UUID,
    actor: User | None = None,
    membership: WorkspaceMembership | None = None,
) -> ArtifactRead:
    artifact = await get_artifact_row(
        db,
        workspace_id=workspace_id,
        artifact_id=artifact_id,
    )
    revisions = list(
        (
            await db.scalars(
                select(ArtifactRevision)
                .where(
                    ArtifactRevision.artifact_id == artifact.id,
                    visible_artifact_revision_filter(workspace_id),
                )
                .order_by(ArtifactRevision.revision_number.desc())
                .limit(100)
            )
        ).all()
    )
    return artifact_to_read(
        artifact, revisions, actor=actor, membership=membership, published_only=True
    )
