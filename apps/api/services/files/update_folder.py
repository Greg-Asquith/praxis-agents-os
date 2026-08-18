# apps/api/services/files/update_folder.py

"""Update workspace file folder metadata."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileFolderRead, FileFolderUpdateRequest
from services.files.folder_utils import (
    FOLDER_NAME_RETRY_LIMIT,
    FOLDER_NAME_UNIQUE_INDEX,
    available_folder_name,
    is_folder_integrity_error,
)
from services.files.utils import get_folder_for_workspace, require_file_write_access
from utils.validation import normalize_optional_text


async def update_folder(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    folder_id: UUID,
    payload: FileFolderUpdateRequest,
) -> FileFolderRead:
    require_file_write_access(membership)
    folder = await get_folder_for_workspace(
        db, workspace=workspace, folder_id=folder_id, for_update=True
    )
    changed_fields: list[str] = []
    if "name" in payload.model_fields_set and payload.name is not None:
        requested = payload.name.strip()
        if requested.lower() != folder.name.lower():
            renamed = False
            for _attempt in range(FOLDER_NAME_RETRY_LIMIT):
                candidate = await available_folder_name(
                    db, workspace_id=workspace.id, requested_name=requested
                )
                try:
                    async with db.begin_nested():
                        folder.name = candidate
                        await db.flush([folder])
                except IntegrityError as exc:
                    if not is_folder_integrity_error(exc, allowed={FOLDER_NAME_UNIQUE_INDEX}):
                        raise
                    continue
                renamed = True
                break
            if not renamed:
                raise ConflictError(
                    "Could not generate a unique folder name",
                    conflicting_resource="file_folder",
                )
            changed_fields.append("name")
        elif requested != folder.name:
            folder.name = requested
            changed_fields.append("name")
    if "description" in payload.model_fields_set:
        description = normalize_optional_text(payload.description)
        if description != folder.description:
            folder.description = description
            changed_fields.append("description")
    if changed_fields:
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.FILE_FOLDER,
            resource_id=folder.id,
            actor=actor,
            details={"action": "rename", "changed_fields": changed_fields},
        )
        await db.refresh(folder)
    return FileFolderRead(
        id=folder.id,
        workspace_id=folder.workspace_id,
        name=folder.name,
        description=folder.description,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )
