# apps/api/services/files/update_file.py

"""Update workspace file metadata."""

from pathlib import PurePosixPath
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileRead, FileUpdateRequest
from services.files.utils import file_to_read, get_file_for_workspace, require_file_write_access
from services.storage.paths import safe_filename


async def update_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    file_id: UUID,
    payload: FileUpdateRequest,
) -> FileRead:
    """Rename a file and update its description without creating a revision."""
    require_file_write_access(membership)
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    changed_fields: list[str] = []
    if "name" in payload.model_fields_set and payload.name is not None:
        filename = safe_filename(payload.name)
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix != file.extension:
            raise AppValidationError("File rename must keep the existing extension", field="name")
        if filename != file.name:
            file.name = filename
            changed_fields.append("name")
    if "description" in payload.model_fields_set and payload.description != file.description:
        file.description = payload.description
        changed_fields.append("description")

    if changed_fields:
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.FILE,
            resource_id=file.id,
            actor=actor,
            details={"action": "rename", "changed_fields": changed_fields},
        )
        await db.refresh(file)
    return file_to_read(file)
