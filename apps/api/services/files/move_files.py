# apps/api/services/files/move_files.py

"""Move one or more logical files between workspace folders."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.files import File
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileMoveRequest, FileMoveResponse
from services.files.utils import (
    file_to_read,
    get_folder_for_workspace,
    require_file_write_access,
)


async def move_files(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: FileMoveRequest,
) -> FileMoveResponse:
    require_file_write_access(membership)
    unique_ids = list(dict.fromkeys(payload.file_ids))
    target = (
        await get_folder_for_workspace(
            db,
            workspace=workspace,
            folder_id=payload.folder_id,
            for_update=True,
        )
        if payload.folder_id is not None
        else None
    )
    files = (
        await db.scalars(
            select(File)
            .where(
                File.workspace_id == workspace.id,
                File.id.in_(unique_ids),
                File.deleted.is_(False),
            )
            .order_by(File.id)
            .with_for_update()
        )
    ).all()
    by_id = {file.id: file for file in files}
    missing = [file_id for file_id in unique_ids if file_id not in by_id]
    if missing:
        raise AppValidationError(
            "One or more files are unavailable",
            field="file_ids",
            details={"file_ids": [str(file_id) for file_id in missing]},
        )
    ordered = [by_id[file_id] for file_id in unique_ids]
    for file in ordered:
        from_folder_id = file.folder_id
        if from_folder_id == payload.folder_id:
            continue
        file.folder_id = payload.folder_id
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
    await db.flush()
    for file in ordered:
        await db.refresh(file)
    folder_name = target.name if target is not None else None
    return FileMoveResponse(files=[file_to_read(file, folder_name=folder_name) for file in ordered])
