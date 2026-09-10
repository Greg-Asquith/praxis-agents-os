# apps/api/services/artifacts/platform/get_version_content.py

"""Reads bounded draft bytes after authentication without a signed capability."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.utils import (
    platform_artifact,
    platform_revision,
    platform_session,
    read_content,
)
from services.artifacts.schemas import ArtifactVersionContentRead


async def get_version_content(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    version_id: UUID | None = None,
) -> ArtifactVersionContentRead:
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        _membership,
    ):
        artifact = await platform_artifact(maintenance_db, artifact_id)
        revision = await platform_revision(
            maintenance_db, artifact, version_id or artifact.current_version_id
        )
        content = await read_content(artifact, revision)
        return ArtifactVersionContentRead(
            content=content.decode("utf-8"),
            content_type=revision.content_type,
            size_bytes=revision.size_bytes,
        )
