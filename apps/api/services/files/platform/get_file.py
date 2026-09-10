# apps/api/services/files/platform/get_file.py

"""Reads platform File metadata, including unpublished drafts."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.files.domain import FileRead
from services.files.platform.utils import get_platform_file, platform_file_to_read, platform_session


async def get_file(db: AsyncSession, *, actor: User, file_id: UUID) -> FileRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id)
        return platform_file_to_read(file, actor)
