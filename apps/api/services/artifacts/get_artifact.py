# apps/api/services/artifacts/get_artifact.py

"""Read one workspace artifact and its versions."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.artifacts import ArtifactRevision
from services.artifacts.schemas import ArtifactRead
from services.artifacts.utils import artifact_to_read, get_artifact_row


async def get_artifact(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    artifact_id: UUID,
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
                .where(ArtifactRevision.artifact_id == artifact.id)
                .order_by(ArtifactRevision.revision_number.desc())
            )
        ).all()
    )
    return artifact_to_read(artifact, revisions)
