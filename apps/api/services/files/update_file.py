# apps/api/services/files/update_file.py

"""Update workspace file metadata."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileRead, FileUpdateRequest
from services.files.utils import (
    apply_file_metadata_update,
    file_to_read,
    get_file_for_workspace,
    get_folder_for_workspace,
    require_file_write_access,
)


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
    target_folder = (
        await get_folder_for_workspace(
            db,
            workspace=workspace,
            folder_id=payload.folder_id,
            for_update=True,
        )
        if "folder_id" in payload.model_fields_set and payload.folder_id is not None
        else None
    )
    file = await get_file_for_workspace(
        db,
        workspace=workspace,
        file_id=file_id,
        for_update=True,
    )
    changed_fields = apply_file_metadata_update(
        file,
        name=payload.name,
        description=payload.description,
        fields_set=payload.model_fields_set,
    )
    folder_name: str | None = None
    if "folder_id" in payload.model_fields_set and payload.folder_id != file.folder_id:
        from_folder_id = file.folder_id
        file.folder_id = payload.folder_id
        changed_fields.append("folder_id")
        folder_name = target_folder.name if target_folder is not None else None
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.FILE,
            resource_id=file.id,
            actor=actor,
            details={
                "action": "move",
                "from_folder_id": str(from_folder_id) if from_folder_id else None,
                "to_folder_id": str(payload.folder_id) if payload.folder_id else None,
            },
        )

    metadata_changed_fields = [field for field in changed_fields if field != "folder_id"]
    if metadata_changed_fields:
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.FILE,
            resource_id=file.id,
            actor=actor,
            details={
                "action": "rename",
                "changed_fields": metadata_changed_fields,
            },
        )
        await db.refresh(file)
    elif changed_fields:
        await db.refresh(file)
    if file.folder_id is not None and folder_name is None:
        folder_name = (
            await get_folder_for_workspace(db, workspace=workspace, folder_id=file.folder_id)
        ).name
    return file_to_read(file, folder_name=folder_name)
