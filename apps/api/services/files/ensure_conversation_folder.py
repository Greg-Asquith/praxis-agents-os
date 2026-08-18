# apps/api/services/files/ensure_conversation_folder.py

"""Resolve the durable output folder for one conversation."""

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.exceptions.general import ConflictError
from models.files import FileFolder
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.folder_utils import (
    FOLDER_CONVERSATION_UNIQUE_INDEX,
    FOLDER_NAME_RETRY_LIMIT,
    FOLDER_NAME_UNIQUE_INDEX,
    available_folder_name,
    is_folder_integrity_error,
)

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps


async def ensure_conversation_folder(deps: "RuntimeDeps") -> FileFolder:
    existing = await deps.db.scalar(
        select(FileFolder).where(
            FileFolder.workspace_id == deps.workspace.id,
            FileFolder.source_conversation_id == deps.conversation.id,
            FileFolder.deleted.is_(False),
        )
    )
    if existing is not None:
        return existing
    folder: FileFolder | None = None
    for _attempt in range(FOLDER_NAME_RETRY_LIMIT):
        candidate = FileFolder(
            workspace_id=deps.workspace.id,
            name=await available_folder_name(
                deps.db,
                workspace_id=deps.workspace.id,
                requested_name=deps.conversation.title or "New Conversation",
            ),
            created_by_agent_id=deps.agent.id,
            source_conversation_id=deps.conversation.id,
        )
        try:
            async with deps.db.begin_nested():
                deps.db.add(candidate)
                await deps.db.flush([candidate])
        except IntegrityError as exc:
            if candidate in deps.db:
                deps.db.expunge(candidate)
            if not is_folder_integrity_error(
                exc,
                allowed={FOLDER_NAME_UNIQUE_INDEX, FOLDER_CONVERSATION_UNIQUE_INDEX},
            ):
                raise
            existing = await deps.db.scalar(
                select(FileFolder).where(
                    FileFolder.workspace_id == deps.workspace.id,
                    FileFolder.source_conversation_id == deps.conversation.id,
                    FileFolder.deleted.is_(False),
                )
            )
            if existing is not None:
                return existing
            continue
        folder = candidate
        break
    if folder is None:
        raise ConflictError(
            "Could not create the conversation output folder",
            conflicting_resource="file_folder",
        )
    await safe_record_operation_audit_event(
        deps.db,
        workspace_id=deps.workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE_FOLDER,
        resource_id=folder.id,
        actor_type=AuditActorType.AGENT,
        actor_id=deps.agent.id,
        actor_display=deps.agent.name,
        requested_by_user_id=deps.user.id,
        details={"name": folder.name, "source_conversation_id": str(deps.conversation.id)},
    )
    return folder
