# apps/api/services/files/delete_folder.py

"""Soft-delete a file folder and every live file it contains."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.files import File
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.utils import get_folder_for_workspace, require_file_write_access

MAX_SYNCHRONOUS_FOLDER_DELETE_FILES = 100
MAX_FOLDER_DELETE_AUDIT_FILE_IDS = 25


async def delete_folder(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    folder_id: UUID,
) -> None:
    require_file_write_access(membership)
    folder = await get_folder_for_workspace(
        db, workspace=workspace, folder_id=folder_id, for_update=True
    )
    file_ids = list(
        await db.scalars(
            select(File.id)
            .where(
                File.workspace_id == workspace.id,
                File.folder_id == folder.id,
                File.deleted.is_(False),
            )
            .order_by(File.id)
            .limit(MAX_SYNCHRONOUS_FOLDER_DELETE_FILES + 1)
        )
    )
    if len(file_ids) > MAX_SYNCHRONOUS_FOLDER_DELETE_FILES:
        raise ConflictError(
            "Folder has too many files to delete in one request. Move or delete some files first.",
            conflicting_resource="file_folder",
            details={"max_file_count": MAX_SYNCHRONOUS_FOLDER_DELETE_FILES},
        )
    files = (
        await db.scalars(
            select(File)
            .where(
                File.workspace_id == workspace.id,
                File.id.in_(file_ids),
                File.folder_id == folder.id,
                File.deleted.is_(False),
            )
            .order_by(File.id)
            .with_for_update()
        )
    ).all()
    for file in files:
        file.soft_delete(deleted_by=actor.id)
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.DELETE,
            resource_type=AuditResourceType.FILE,
            resource_id=file.id,
            actor=actor,
            details={"filename": file.name},
        )
    folder.soft_delete(deleted_by=actor.id)
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.FILE_FOLDER,
        resource_id=folder.id,
        actor=actor,
        details={
            "name": folder.name,
            "file_count": len(files),
            "file_ids": [str(file.id) for file in files[:MAX_FOLDER_DELETE_AUDIT_FILE_IDS]],
            "file_ids_truncated": len(files) > MAX_FOLDER_DELETE_AUDIT_FILE_IDS,
        },
    )
