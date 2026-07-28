# apps/api/services/files/append_file_revision.py

"""Append an immutable revision to a logical file."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.files import FileRevision
from models.workspace import Workspace
from services.files.create_file_with_revision import FileRevisionWriteResult
from services.files.revision_actor import FileRevisionActor
from services.files.utils import (
    get_file_for_workspace,
    private_ref_from_key,
    revision_object_key,
    sha256_hex,
)
from services.storage.factory import get_storage_provider
from services.storage.utils import put_new_object_with_cleanup


async def append_file_revision(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
    content: bytes,
    actor: FileRevisionActor,
    revision_kind: str = "edit",
    expected_current_revision_id: UUID | None = None,
) -> FileRevisionWriteResult:
    """Append a revision under a row lock and advance the file pointer."""
    actor.validate()
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    if (
        expected_current_revision_id is not None
        and file.current_revision_id != expected_current_revision_id
    ):
        raise ConflictError(
            "File has changed",
            conflicting_resource="file",
            details={"current_revision_id": str(file.current_revision_id)},
        )
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, file.extension)
    content_hash = sha256_hex(content)
    revision = FileRevision(
        id=revision_id,
        file_id=file.id,
        workspace_id=workspace.id,
        revision_number=file.revision_count + 1,
        revision_kind=revision_kind,
        content_type=file.content_type,
        extension=file.extension,
        size_bytes=len(content),
        content_hash=content_hash,
        object_key=object_key,
        **actor.columns(),
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = revision.revision_number
    file.size_bytes = revision.size_bytes
    file.content_hash = revision.content_hash
    file.processing_status = "ready"
    file.processing_error = None
    await db.flush()
    await db.refresh(file)
    await put_new_object_with_cleanup(
        get_storage_provider(),
        private_ref_from_key(object_key),
        content,
        content_type=file.content_type,
    )
    return FileRevisionWriteResult(file=file, revision=revision, bytes_written=len(content))
