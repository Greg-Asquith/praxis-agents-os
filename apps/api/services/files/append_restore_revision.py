# apps/api/services/files/append_restore_revision.py

"""Appends a revision that restores an earlier one."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileRevision
from models.user import User
from services.files.set_processing_state_for_revision import set_processing_state_for_revision
from utils.content import ContentScope


async def append_restore_revision(
    db: AsyncSession, *, file: File, source: FileRevision, actor: User
) -> FileRevision:
    """Appends an immutable restore revision after the caller locks and validates the parent."""
    revision = FileRevision(
        id=uuid4(),
        file_id=file.id,
        workspace_id=file.workspace_id,
        scope=file.scope,
        revision_number=file.revision_count + 1,
        revision_kind="restore",
        content_type=source.content_type,
        extension=source.extension,
        size_bytes=source.size_bytes,
        content_hash=source.content_hash,
        object_key=source.object_key,
        created_by_user_id=actor.id,
        restored_from_revision_id=source.id,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    if file.scope == ContentScope.PLATFORM and not file.is_published:
        # A fresh draft can process after withdrawal cancelled the previous revision.
        file.published_revision_id = None
    file.revision_count = revision.revision_number
    file.content_type = revision.content_type
    file.extension = revision.extension
    file.size_bytes = revision.size_bytes
    file.content_hash = revision.content_hash
    await set_processing_state_for_revision(
        db, file=file, revision=revision, initiated_by_user_id=actor.id
    )
    await db.flush()
    return revision
