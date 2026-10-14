# apps/api/services/files/folder_utils.py

"""Helpers shared by human and agent folder operations."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from core.exceptions.general import ConflictError
from models.files import FileFolder
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.utils import normalize_required_text

if TYPE_CHECKING:
    from services.agents.runtime.context import RuntimeDeps

FOLDER_NAME_UNIQUE_INDEX = "uq_file_folders_workspace_name_live"
FOLDER_CONVERSATION_UNIQUE_INDEX = "uq_file_folders_workspace_conversation_live"
FOLDER_SOURCE_FILE_UNIQUE_INDEX = "uq_file_folders_workspace_source_file_live"
FOLDER_NAME_RETRY_LIMIT = 10


def is_folder_integrity_error(exc: IntegrityError, *, allowed: set[str]) -> bool:
    """Return whether Postgres attributed an integrity error to an allowed folder index."""
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name in allowed:
        return True
    return any(name in str(exc) for name in allowed)


async def folder_by_name(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    name: str,
) -> FileFolder | None:
    normalized = normalize_required_text(name)
    return await db.scalar(
        select(FileFolder).where(
            FileFolder.workspace_id == workspace_id,
            FileFolder.deleted.is_(False),
            func.lower(FileFolder.name) == normalized.lower(),
        )
    )


async def available_folder_name(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    requested_name: str,
) -> str:
    """Choose a case-insensitively unique live folder name with a numeric suffix."""
    base = normalize_required_text(requested_name)
    existing = set(
        await db.scalars(
            select(func.lower(FileFolder.name)).where(
                FileFolder.workspace_id == workspace_id,
                FileFolder.deleted.is_(False),
            )
        )
    )
    if base.lower() not in existing:
        return base
    suffix_number = 2
    while True:
        suffix = f" ({suffix_number})"
        candidate = f"{base[: 255 - len(suffix)]}{suffix}"
        if candidate.lower() not in existing:
            return candidate
        suffix_number += 1


async def ensure_linked_folder(
    deps: "RuntimeDeps",
    *,
    link: InstrumentedAttribute[Any],
    link_id: UUID,
    link_index: str,
    name: str,
) -> FileFolder:
    """Returns the live folder linked to a conversation or File, creating it once."""
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
