# apps/api/services/files/platform/get_file_content.py

"""Reads platform draft text without issuing a download capability."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.files.contract import contract_for_content_type
from services.files.domain import FileRevisionContentRead
from services.files.platform.utils import (
    get_platform_file,
    get_platform_revision,
    platform_session,
    read_revision_bytes,
    read_revision_markdown,
)
from utils.digests import sha256_hex


async def get_file_content(
    db: AsyncSession, *, actor: User, file_id: UUID, revision_id: UUID | None = None
) -> FileRevisionContentRead:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id)
        revision = await get_platform_revision(
            maintenance_db, file=file, revision_id=revision_id or file.current_revision_id
        )
        entry = contract_for_content_type(revision.content_type)
        if entry.editable:
            data = await read_revision_bytes(revision)
            content_type = revision.content_type
        elif entry.ingestible:
            data = await read_revision_markdown(revision)
            content_type = "text/markdown"
        else:
            raise AppValidationError("File revision does not support text content reads")
        return FileRevisionContentRead(
            file_id=file.id,
            revision_id=revision.id,
            revision_number=revision.revision_number,
            content_type=content_type,
            size_bytes=len(data),
            content_hash=sha256_hex(data),
            content=data.decode("utf-8", errors="replace"),
        )
