# apps/api/services/files/platform/get_file_preview.py

"""Reads bounded platform preview bytes through authenticated maintenance access."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.files.contract import FileCategory, contract_for_content_type
from services.files.platform.utils import (
    get_platform_file,
    get_platform_revision,
    platform_session,
    read_revision_bytes,
)


async def get_file_preview(
    db: AsyncSession, *, actor: User, file_id: UUID, revision_id: UUID | None = None
) -> tuple[bytes, str]:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id)
        revision = await get_platform_revision(
            maintenance_db, file=file, revision_id=revision_id or file.current_revision_id
        )
        entry = contract_for_content_type(revision.content_type)
        if entry.category not in {FileCategory.IMAGE, FileCategory.VIDEO} and (
            entry.content_type != "application/pdf"
        ):
            raise AppValidationError("Previews are available for images, videos, and PDFs")
        return await read_revision_bytes(revision), revision.content_type
