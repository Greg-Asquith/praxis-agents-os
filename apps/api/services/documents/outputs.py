# apps/api/services/documents/outputs.py

"""Durable persistence for Files that tools create or edit. Runs in the host process."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.files import FileFolder
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.append_file_revision import append_file_revision
from services.files.contract import contract_for_content_type, max_size_bytes
from services.files.create_conversation_file_references import (
    create_conversation_file_references,
)
from services.files.create_file_with_revision import create_file_with_revision
from services.files.ensure_conversation_folder import ensure_conversation_folder
from services.files.resolve_folder_by_name import resolve_folder_by_name
from services.files.revision_actor import FileRevisionActor
from services.files.utils import get_folder_for_workspace


@dataclass(frozen=True)
class EditTarget:
    file_id: UUID
    revision_id: UUID
    name: str
    media_type: str


class OutputFolder(BaseModel):
    id: UUID
    name: str


class StoredOutput(BaseModel):
    name: str
    size_bytes: int
    media_type: str
    reference: FileReference
    updated_existing: bool = False
    revision_id: UUID | None = None
    revision_number: int | None = None
    folder: OutputFolder | None = None


@dataclass
class OutputFolderResolver:
    """Resolves the folder for new Files once: a named folder, or the conversation's own."""

    requested_name: str | None
    resolved: FileFolder | None = None

    async def get(self, deps: RuntimeDeps) -> FileFolder:
        if self.resolved is None:
            folder = (
                await resolve_folder_by_name(
                    deps.db,
                    workspace=deps.workspace,
                    agent=deps.agent,
                    requested_by=deps.user,
                    name=self.requested_name,
                )
                if self.requested_name is not None
                else await ensure_conversation_folder(deps)
            )
            try:
                self.resolved = await get_folder_for_workspace(
                    deps.db,
                    workspace=deps.workspace,
                    folder_id=folder.id,
                    for_update=True,
                )
            except NotFoundError as exc:
                raise ConflictError(
                    "Output folder was deleted while the output was being saved",
                    conflicting_resource="file_folder",
                ) from exc
        return self.resolved


async def save_file_edit(
    deps: RuntimeDeps,
    *,
    target: EditTarget,
    content: bytes,
    details: Mapping[str, Any],
) -> StoredOutput:
    """Appends a revision to the target File and records one File update audit event.

    Raises `ConflictError` when the File moved past `target.revision_id`, and
    `AppValidationError` when the content passes the File's size limit.
    """
    _check_size(content, target.media_type, "Edited file exceeds its governed size limit")
    result = await append_file_revision(
        deps.db,
        workspace=deps.workspace,
        file_id=target.file_id,
        content=content,
        actor=FileRevisionActor(agent_id=deps.agent.id),
        revision_kind="edit",
        expected_current_revision_id=target.revision_id,
    )
    await safe_record_operation_audit_event(
        deps.db,
        workspace_id=deps.workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.FILE,
        resource_id=result.file.id,
        actor_type=AuditActorType.AGENT,
        actor_id=deps.agent.id,
        actor_display=deps.agent.name,
        requested_by_user_id=deps.user.id,
        details={
            "filename": result.file.name,
            "size_bytes": result.bytes_written,
            "revision_id": str(result.revision.id),
            "revision_number": result.revision.revision_number,
            "revision_kind": result.revision.revision_kind,
            "content_hash": result.revision.content_hash,
            **details,
        },
    )
    return StoredOutput(
        name=result.file.name,
        size_bytes=result.bytes_written,
        media_type=result.file.content_type,
        reference=FileReference(
            entity_id=result.file.id,
            label=result.file.name,
            description=(
                f"Updated file · revision {result.revision.revision_number} · "
                f"{result.bytes_written:,} bytes"
            ),
        ),
        updated_existing=True,
        revision_id=result.revision.id,
        revision_number=result.revision.revision_number,
    )


async def save_new_file(
    deps: RuntimeDeps,
    *,
    name: str,
    content: bytes,
    media_type: str,
    folder: OutputFolderResolver,
    details: Mapping[str, Any],
) -> StoredOutput:
    """Creates a File in the resolved folder, links it to the conversation, and audits it.

    The extension follows the media type. Raises `AppValidationError` when the
    content passes the type's size limit or the name is invalid.
    """
    entry = contract_for_content_type(media_type)
    extension = next((item for item in entry.extensions if name.lower().endswith(item)), None)
    if extension is None:
        # A dot inside the name isn't an extension, so the type's own is appended.
        extension = entry.extensions[0]
        name = f"{name}{extension}"
    _check_size(content, media_type, "Generated file exceeds its governed size limit")
    resolved_folder = await folder.get(deps)
    result = await create_file_with_revision(
        deps.db,
        workspace=deps.workspace,
        name=name,
        content=content,
        content_type=entry.content_type,
        extension=extension,
        actor=FileRevisionActor(agent_id=deps.agent.id),
        resolved_folder=resolved_folder,
    )
    await create_conversation_file_references(
        deps.db,
        workspace_id=deps.workspace.id,
        conversation_id=deps.conversation.id,
        file_ids=[result.file.id],
        created_by_user_id=deps.user.id,
    )
    await safe_record_operation_audit_event(
        deps.db,
        workspace_id=deps.workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE,
        resource_id=result.file.id,
        actor_type=AuditActorType.AGENT,
        actor_id=deps.agent.id,
        actor_display=deps.agent.name,
        requested_by_user_id=deps.user.id,
        details={
            "filename": result.file.name,
            "size_bytes": result.bytes_written,
            "revision_id": str(result.revision.id),
            "revision_kind": result.revision.revision_kind,
            "content_hash": result.revision.content_hash,
            "folder_id": str(resolved_folder.id),
            **details,
        },
    )
    return StoredOutput(
        name=result.file.name,
        size_bytes=result.bytes_written,
        media_type=result.file.content_type,
        reference=FileReference(
            entity_id=result.file.id,
            label=result.file.name,
            description=f"Generated file · {result.bytes_written:,} bytes",
        ),
        revision_id=result.revision.id,
        revision_number=result.revision.revision_number,
        folder=OutputFolder(id=resolved_folder.id, name=resolved_folder.name),
    )


def _check_size(content: bytes, media_type: str, message: str) -> None:
    maximum = min(
        max_size_bytes(contract_for_content_type(media_type)), settings.MAX_FILE_SIZE_AGENT_FILE
    )
    if len(content) > maximum:
        raise AppValidationError(
            message,
            field="content",
            details={"size_bytes": len(content), "max_bytes": maximum},
        )
