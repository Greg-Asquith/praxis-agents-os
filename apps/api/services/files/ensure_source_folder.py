# apps/api/services/files/ensure_source_folder.py

"""Resolve the durable output folder linked to a conversation or an original File."""

from pathlib import PurePath
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute

from core.exceptions.general import ConflictError
from models.files import File, FileFolder
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.folder_utils import (
    FOLDER_CONVERSATION_UNIQUE_INDEX,
    FOLDER_NAME_RETRY_LIMIT,
    FOLDER_NAME_UNIQUE_INDEX,
    FOLDER_SOURCE_FILE_UNIQUE_INDEX,
    available_folder_name,
    is_folder_integrity_error,
)

if TYPE_CHECKING:
    from uuid import UUID

    from services.agents.runtime.context import RuntimeDeps


async def ensure_conversation_folder(deps: "RuntimeDeps") -> FileFolder:
    return await _ensure_linked_folder(
        deps,
        link=FileFolder.source_conversation_id,
        link_id=deps.conversation.id,
        link_index=FOLDER_CONVERSATION_UNIQUE_INDEX,
        name=deps.conversation.title or "New Conversation",
    )


async def ensure_source_file_folder(deps: "RuntimeDeps", source: File) -> FileFolder:
    """Returns the folder for outputs derived from a File, named after it.

    A File already inside another File's folder is itself derived, so its outputs
    join that folder and every edit of one original stays together.
    """
    if source.folder_id is not None:
        current = await deps.db.scalar(
            select(FileFolder).where(
                FileFolder.id == source.folder_id,
                FileFolder.workspace_id == deps.workspace.id,
                FileFolder.source_file_id.is_not(None),
                FileFolder.deleted.is_(False),
            )
        )
        if current is not None:
            return current
    return await _ensure_linked_folder(
        deps,
        link=FileFolder.source_file_id,
        link_id=source.id,
        link_index=FOLDER_SOURCE_FILE_UNIQUE_INDEX,
        name=PurePath(source.name).stem or source.name,
    )


async def _ensure_linked_folder(
    deps: "RuntimeDeps",
    *,
    link: InstrumentedAttribute[Any],
    link_id: "UUID",
    link_index: str,
    name: str,
) -> FileFolder:
    linked = (
        select(FileFolder)
        .where(
            FileFolder.workspace_id == deps.workspace.id,
            link == link_id,
            FileFolder.deleted.is_(False),
        )
        .limit(1)
    )
    existing = await deps.db.scalar(linked)
    if existing is not None:
        return existing
    folder: FileFolder | None = None
    for _attempt in range(FOLDER_NAME_RETRY_LIMIT):
        candidate = FileFolder(
            workspace_id=deps.workspace.id,
            name=await available_folder_name(
                deps.db, workspace_id=deps.workspace.id, requested_name=name
            ),
            created_by_agent_id=deps.agent.id,
            **{link.key: link_id},
        )
        try:
            async with deps.db.begin_nested():
                deps.db.add(candidate)
                await deps.db.flush([candidate])
        except IntegrityError as exc:
            if candidate in deps.db:
                deps.db.expunge(candidate)
            if not is_folder_integrity_error(exc, allowed={FOLDER_NAME_UNIQUE_INDEX, link_index}):
                raise
            existing = await deps.db.scalar(linked)
            if existing is not None:
                return existing
            continue
        folder = candidate
        break
    if folder is None:
        raise ConflictError(
            "Could not create the output folder", conflicting_resource="file_folder"
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
        details={"name": folder.name, link.key: str(link_id)},
    )
    return folder
