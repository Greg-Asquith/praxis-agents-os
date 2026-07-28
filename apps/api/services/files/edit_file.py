# apps/api/services/files/edit_file.py

"""Append a text edit revision to a workspace file."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.append_file_revision import append_file_revision
from services.files.contract import is_editable
from services.files.domain import FileEditRequest, FileRead
from services.files.revision_actor import FileRevisionActor
from services.files.utils import (
    file_to_read,
    get_file_for_workspace,
    require_file_write_access,
)


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
    )
    if not is_editable(file.content_type):
        raise AppValidationError("File type does not support text edits", field="content")

    data = payload.content.encode("utf-8")
    if len(data) > settings.FILES_MAX_TEXT_EDIT_BYTES:
        raise AppValidationError("Edited file content is too large", field="content")

    result = await append_file_revision(
        db,
        workspace=workspace,
        file_id=file.id,
        content=data,
        actor=FileRevisionActor(user_id=actor.id),
        expected_current_revision_id=payload.expected_current_revision_id,
    )

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.FILE,
        resource_id=result.file.id,
        actor=actor,
        details={"action": "edit", "revision_id": str(result.revision.id)},
    )
    return file_to_read(result.file)
