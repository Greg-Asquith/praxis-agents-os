# apps/api/services/files/restore_file_revision.py

"""Restore a prior file revision by appending a roll-forward revision."""

from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.files import FileRevision
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileRead, FileRestoreRequest
from services.files.utils import file_to_read, get_file_for_workspace, require_file_write_access


async def restore_file_revision(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    file_id: UUID,
    payload: FileRestoreRequest,
) -> FileRead:
    """Append a restore revision that reuses the selected revision's object."""
    require_file_write_access(membership)
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    if file.current_revision_id != payload.expected_current_revision_id:
        raise ConflictError(
            "File has changed",
            conflicting_resource="file",
            details={"current_revision_id": str(file.current_revision_id)},
        )
    if payload.revision_id == file.current_revision_id:
        raise AppValidationError("Cannot restore the current revision", field="revision_id")

    source = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == payload.revision_id,
            FileRevision.file_id == file.id,
            FileRevision.workspace_id == workspace.id,
        )
    )
    if source is None:
        raise NotFoundError(
            "File revision not found",
            resource_type="file_revision",
            resource_id=str(payload.revision_id),
        )

    revision = FileRevision(
        id=uuid4(),
        file_id=file.id,
        workspace_id=workspace.id,
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
    file.revision_count = revision.revision_number
    file.content_type = revision.content_type
    file.extension = revision.extension
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
        details={"action": "restore", "restored_from_revision_id": str(source.id)},
    )
    await db.refresh(file)
    return file_to_read(file)
