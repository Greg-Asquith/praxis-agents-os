# apps/api/services/files/create_folder.py

"""Create a workspace file folder."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.files import FileFolder
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.files.domain import FileFolderCreateRequest, FileFolderRead
from services.files.folder_utils import (
    FOLDER_NAME_RETRY_LIMIT,
    FOLDER_NAME_UNIQUE_INDEX,
    available_folder_name,
    is_folder_integrity_error,
)
from services.files.utils import require_file_write_access
from utils.validation import normalize_optional_text


async def create_folder(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: FileFolderCreateRequest,
) -> FileFolderRead:
    require_file_write_access(membership)
    folder: FileFolder | None = None
    for _attempt in range(FOLDER_NAME_RETRY_LIMIT):
        candidate = FileFolder(
            workspace_id=workspace.id,
            name=await available_folder_name(
                db, workspace_id=workspace.id, requested_name=payload.name
            ),
            description=normalize_optional_text(payload.description),
            created_by_user_id=actor.id,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush([candidate])
        except IntegrityError as exc:
            if candidate in db:
                db.expunge(candidate)
            if not is_folder_integrity_error(exc, allowed={FOLDER_NAME_UNIQUE_INDEX}):
                raise
            continue
        folder = candidate
        break
    if folder is None:
        raise ConflictError(
            "Could not generate a unique folder name",
            conflicting_resource="file_folder",
        )
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE_FOLDER,
        resource_id=folder.id,
        actor=actor,
        details={"name": folder.name},
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
