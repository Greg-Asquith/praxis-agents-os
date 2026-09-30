# apps/api/services/documents/outputs.py

"""Durable persistence for Files that tools create or edit. Runs in the host process."""

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ToolFailed

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.files import FileFolder
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import ArtifactReference, FileReference
from services.artifacts import create_artifact as create_artifact_service
from services.artifacts.domain import CREATABLE_ARTIFACT_TYPES
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

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")
_ARTIFACT_TYPE_BY_EXTENSION = {
    ".csv": "csv",
    ".html": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mmd": "mermaid",
}


@dataclass(frozen=True)
class EditTarget:
    file_id: UUID
    revision_id: UUID
    name: str
    media_type: str


@dataclass(frozen=True)
class CapturedOutput:
    name: str
    content: bytes
    media_type: str


class OutputFolder(BaseModel):
    id: UUID
    name: str


class StoredOutput(BaseModel):
    kind: Literal["artifact", "file"]
    name: str
    size_bytes: int
    media_type: str
    reference: ArtifactReference | FileReference
    updated_existing: bool = False
    revision_id: UUID | None = None
    revision_number: int | None = None
    sandbox_name: str | None = Field(default=None, exclude=True)
    folder: OutputFolder | None = None


def safe_sandbox_name(value: object) -> str:
    """Normalises an output filename without retaining directory components."""
    raw = PurePath(str(value or "sandbox-output.bin")).name
    cleaned = _SAFE_FILENAME.sub("_", raw).strip(" .")
    return (cleaned or "sandbox-output.bin")[:255]


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
        kind="file",
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
    extension = PurePath(name).suffix.lower()
    if extension not in entry.extensions:
        extension = entry.extensions[0]
        name = f"{PurePath(name).stem}{extension}"
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
        kind="file",
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


async def persist_sandbox_outputs(
    deps: RuntimeDeps,
    *,
    task: str,
    captured: Sequence[CapturedOutput],
    input_file_ids: Sequence[UUID],
    input_revision_ids: Sequence[UUID],
    edit_target: EditTarget | None = None,
    folder: str | None = None,
) -> tuple[list[StoredOutput], list[str]]:
    """Saves provider sandbox outputs: at most one edit of `edit_target`, the rest as new Files."""
    stored: list[StoredOutput] = []
    skipped: list[str] = []
    output_folder = OutputFolderResolver(requested_name=folder)
    details = {
        "source": "native_run_code",
        "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
        "input_file_ids": [str(value) for value in input_file_ids],
        "input_revision_ids": [str(value) for value in input_revision_ids],
    }
    remaining = captured
    if edit_target is not None:
        edit_output = _select_edited_sandbox_output(captured, edit_target)
        try:
            edited = await save_file_edit(
                deps, target=edit_target, content=edit_output.content, details=details
            )
        except (AppValidationError, AuthorizationError, UnicodeDecodeError, ValueError) as exc:
            raise ToolFailed(
                "The selected edited output could not be saved as a new revision: "
                f"{getattr(exc, 'message', str(exc))}"
            ) from exc
        except ConflictError as exc:
            raise ToolFailed(
                "The selected file changed while the sandbox was editing it. Run the edit again "
                "against the latest revision."
            ) from exc
        stored.append(
            edited.model_copy(update={"sandbox_name": safe_sandbox_name(edit_output.name)})
        )
        remaining = [item for item in captured if item is not edit_output]
    for item in remaining:
        try:
            stored.append(await _persist_sandbox_output(deps, item, output_folder, details))
        except (AppValidationError, ConflictError, UnicodeDecodeError, ValueError) as exc:
            skipped.append(f"{item.name}: {getattr(exc, 'message', str(exc))}")
    return stored, skipped


def _select_edited_sandbox_output(
    captured: Sequence[CapturedOutput],
    edit_target: EditTarget,
) -> CapturedOutput:
    target_contract = contract_for_content_type(edit_target.media_type)
    candidates = [
        item
        for item in captured
        if item.media_type == target_contract.content_type
        or (
            item.media_type == "application/octet-stream"
            and PurePath(safe_sandbox_name(item.name)).suffix.lower() in target_contract.extensions
        )
    ]
    if not candidates:
        raise ToolFailed(
            f"The sandbox did not produce an edited output compatible with {edit_target.name!r}. "
            "Create exactly one complete modified file in the source format."
        )
    if len(candidates) > 1:
        names = ", ".join(repr(safe_sandbox_name(item.name)) for item in candidates[:5])
        suffix = " …" if len(candidates) > 5 else ""
        raise ToolFailed(
            f"The sandbox produced multiple possible edits for {edit_target.name!r}: "
            f"{names}{suffix}. Create exactly one complete modified file in the source format."
        )
    return candidates[0]


async def _persist_sandbox_output(
    deps: RuntimeDeps,
    output: CapturedOutput,
    output_folder: OutputFolderResolver,
    details: Mapping[str, Any],
) -> StoredOutput:
    name = safe_sandbox_name(output.name)
    artifact_type = _ARTIFACT_TYPE_BY_EXTENSION.get(PurePath(name).suffix.lower())
    if artifact_type in CREATABLE_ARTIFACT_TYPES:
        text = output.content.decode("utf-8")
        artifact, _revision = await create_artifact_service(
            deps.db,
            workspace=deps.workspace,
            title=PurePath(name).stem or "Sandbox output",
            artifact_type=artifact_type,
            content=text,
            agent=deps.agent,
            conversation=deps.conversation,
            run=deps.run,
        )
        return StoredOutput(
            kind="artifact",
            name=artifact.title,
            size_bytes=len(output.content),
            media_type=output.media_type,
            reference=ArtifactReference(
                entity_id=artifact.id,
                label=artifact.title,
                description=f"{artifact_type.title()} artifact",
            ),
        )
    return await save_new_file(
        deps,
        name=name,
        content=output.content,
        media_type=output.media_type,
        folder=output_folder,
        details=details,
    )
