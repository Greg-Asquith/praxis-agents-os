# apps/api/services/artifacts/platform/get_artifact.py

"""Returns an authenticated super-admin Artifact review."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import PlatformArtifactRead
from services.artifacts.platform.utils import platform_artifact, platform_session, to_read


async def get_artifact(
    db: AsyncSession, *, actor: User, workspace: Workspace, artifact_id: UUID
) -> PlatformArtifactRead:
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        artifact = await platform_artifact(maintenance_db, artifact_id)
        return await to_read(maintenance_db, artifact, actor, membership)
