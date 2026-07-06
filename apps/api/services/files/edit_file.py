# apps/api/services/files/edit_file.py

"""Append a text edit revision to a workspace file."""

from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.files import FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.contract import is_editable
from services.files.domain import FileEditRequest, FileRead
from services.files.utils import (
    file_to_read,
    get_file_for_workspace,
    private_ref_from_key,
    require_file_write_access,
    revision_object_key,
    sha256_hex,
)
from services.storage.factory import get_storage_provider


async def edit_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    file_id: UUID,
    payload: FileEditRequest,
) -> FileRead:
    """Append an editable text revision using optimistic concurrency."""
    require_file_write_access(membership)
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    if not is_editable(file.content_type):
        raise AppValidationError("File type does not support text edits", field="content")
    if file.current_revision_id != payload.expected_current_revision_id:
        raise ConflictError(
            "File has changed",
            conflicting_resource="file",
            details={"current_revision_id": str(file.current_revision_id)},
        )

    data = payload.content.encode("utf-8")
    if len(data) > settings.FILES_MAX_TEXT_EDIT_BYTES:
        raise AppValidationError("Edited file content is too large", field="content")

    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, file.extension)
    provider = get_storage_provider()
    stored = await provider.put_object(
        private_ref_from_key(object_key),
        data,
        content_type=file.content_type,
    )
    content_hash = sha256_hex(data)
    revision = FileRevision(
        id=revision_id,
        file_id=file.id,
        workspace_id=workspace.id,
        revision_number=file.revision_count + 1,
        revision_kind="edit",
        content_type=file.content_type,
        extension=file.extension,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
        object_key=object_key,
        created_by_user_id=actor.id,
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

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.FILE,
        resource_id=file.id,
        actor=actor,
        details={"action": "edit", "revision_id": str(revision.id)},
    )
    await db.refresh(file)
    return file_to_read(file)
