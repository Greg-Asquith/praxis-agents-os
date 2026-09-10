# apps/api/services/files/platform/get_file_content.py

"""Reads platform draft text without issuing a download capability."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.files.contract import is_editable
from services.files.domain import FileRevisionContentRead
from services.files.platform.utils import (
    get_platform_file,
    get_platform_revision,
    platform_session,
    read_revision_bytes,
)


async def get_file_content(
    db: AsyncSession, *, actor: User, file_id: UUID, revision_id: UUID | None = None
) -> FileRevisionContentRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id)
        revision = await get_platform_revision(
            maintenance_db, file=file, revision_id=revision_id or file.current_revision_id
        )
        if not is_editable(revision.content_type):
            raise AppValidationError("File revision does not support text content reads")
        data = await read_revision_bytes(revision)
        return FileRevisionContentRead(
            file_id=file.id,
            revision_id=revision.id,
            revision_number=revision.revision_number,
            content_type=revision.content_type,
            size_bytes=revision.size_bytes,
            content_hash=revision.content_hash,
            content=data.decode("utf-8", errors="replace"),
        )
