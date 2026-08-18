# apps/api/services/files/resolve_folder_by_name.py

"""Resolve or create an agent-owned file folder by name."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent import Agent
from models.files import FileFolder
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.folder_utils import (
    FOLDER_NAME_RETRY_LIMIT,
    FOLDER_NAME_UNIQUE_INDEX,
    available_folder_name,
    folder_by_name,
    is_folder_integrity_error,
)


async def resolve_folder_by_name(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    requested_by: User,
    name: str,
) -> FileFolder:
    existing = await folder_by_name(db, workspace_id=workspace.id, name=name)
    if existing is not None:
        return existing
    folder: FileFolder | None = None
    for _attempt in range(FOLDER_NAME_RETRY_LIMIT):
        candidate = FileFolder(
            workspace_id=workspace.id,
            name=await available_folder_name(db, workspace_id=workspace.id, requested_name=name),
            created_by_agent_id=agent.id,
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
            existing = await folder_by_name(db, workspace_id=workspace.id, name=name)
            if existing is not None:
                return existing
            continue
        folder = candidate
        break
    if folder is None:
        raise ConflictError(
            "Could not generate a unique folder name",
            conflicting_resource="file_folder",
        )
    await safe_record_operation_audit_event(
        db,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE_FOLDER,
        resource_id=folder.id,
        actor_type=AuditActorType.AGENT,
        actor_id=agent.id,
        actor_display=agent.name,
        requested_by_user_id=requested_by.id,
        details={"name": folder.name},
    )
    return folder
