# apps/api/services/files/reserve_file_revision.py

"""Retains cleanup ownership for a server-created File before storage writes."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_async_db_session_factory, set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.files import FileUpload
from services.files.contract import require_matching_pair
from services.files.utils import revision_object_key, sha256_hex


async def reserve_file_revision(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    content: bytes,
    content_type: str,
    extension: str,
) -> FileUpload:
    """Commits an isolated reservation and locks it until the caller settles."""
    contract = require_matching_pair(content_type, extension)
    file_id, revision_id, reservation_id = uuid4(), uuid4(), uuid4()
    async with get_async_db_session_factory()() as reservation_db:
        await set_session_tenant_context(reservation_db, workspace_id=workspace_id, user_id=user_id)
        reservation_db.add(
            FileUpload(
                id=reservation_id,
                scope="workspace",
                workspace_id=workspace_id,
                file_id=file_id,
                revision_id=revision_id,
                object_key=revision_object_key(workspace_id, file_id, revision_id, extension),
                filename=name,
                content_type=contract.content_type,
                declared_size_bytes=len(content),
                declared_content_hash=sha256_hex(content),
                created_by_user_id=user_id,
                expires_at=datetime.now(UTC) + timedelta(hours=settings.FILES_UPLOAD_EXPIRY_HOURS),
            )
        )
        await reservation_db.commit()
    reservation = await db.scalar(
        select(FileUpload)
        .where(FileUpload.id == reservation_id, FileUpload.workspace_id == workspace_id)
        .with_for_update()
    )
    if reservation is None:
        raise NotFoundError("File copy expired. Start a new copy.")
    return reservation
