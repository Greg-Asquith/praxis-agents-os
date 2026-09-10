# apps/api/services/files/platform/publish_file.py

"""Publishes a reviewed platform File revision atomically."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from services.files.domain import FileRead, PlatformFilePublishRequest
from services.files.platform.utils import (
    get_platform_file,
    get_platform_revision,
    platform_file_to_read,
    platform_session,
    publish_locked_revision,
)


async def publish_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    file_id: UUID,
    payload: PlatformFilePublishRequest,
) -> FileRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id, for_update=True)
        if file.current_revision_id != payload.expected_current_revision_id:
            raise ConflictError("File has changed", conflicting_resource="file")
        revision = await get_platform_revision(
            maintenance_db, file=file, revision_id=file.current_revision_id
        )
        await publish_locked_revision(
            maintenance_db,
            file=file,
            revision=revision,
            actor=actor,
            request=request,
        )
        return platform_file_to_read(file, actor)
