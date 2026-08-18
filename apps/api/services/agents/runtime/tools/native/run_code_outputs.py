# apps/api/services/agents/runtime/tools/native/run_code_outputs.py

"""Bounded capture and durable persistence for native ``run_code`` outputs."""

import hashlib
import mimetypes
import re
from collections.abc import AsyncIterator, Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Literal
from urllib.parse import unquote
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ToolFailed
from pydantic_ai.messages import (
    FilePart,
    ModelMessage,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.files import FileFolder
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import ArtifactReference, FileReference
from services.agents.runtime.tools.native.run_code_file_bridge import (
    RunCodeEditTarget,
    safe_sandbox_name,
)
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

_TRUNCATED_MARKER = "\n[truncated]"
_SANDBOX_MARKDOWN_LINK = re.compile(
    r"(?P<label>\[[^\]]+\])\((?P<target>sandbox:[^)]+)\)",
    flags=re.IGNORECASE,
)
_ARTIFACT_TYPE_BY_EXTENSION = {
    ".csv": "csv",
    ".html": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".mmd": "mermaid",
}


@dataclass(frozen=True)
class CapturedSandboxFile:
    name: str
    content: bytes
    media_type: str


class RunCodeFolder(BaseModel):
    id: UUID
    name: str


class RunCodeStoredOutput(BaseModel):
    kind: Literal["artifact", "file"]
    name: str
    size_bytes: int
    media_type: str
    reference: ArtifactReference | FileReference
    updated_existing: bool = False
    revision_id: UUID | None = None
    revision_number: int | None = None
    sandbox_name: str | None = Field(default=None, exclude=True)
    folder: RunCodeFolder | None = None


@dataclass
class _OutputFolderResolver:
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
                    "Output folder was deleted while the sandbox output was being saved",
                    conflicting_resource="file_folder",
                ) from exc
        return self.resolved


@dataclass
class _RetrievalBudget:
    """Bounds provider output downloads before the bytes enter worker memory."""

    files_remaining: int
    bytes_remaining: int
    skipped: list[str]
    _limit_noted: bool = field(default=False, repr=False)

    def exhausted(self) -> bool:
        if self.files_remaining > 0 and self.bytes_remaining > 0:
            return False
        if not self._limit_noted:
            self._limit_noted = True
            self.skipped.append("Further sandbox outputs were not retrieved: output limits reached")
        return True

    def admit(self, name: str, declared_size: int | None) -> bool:
        if self.exhausted():
            return False
        if declared_size is not None and declared_size > self.bytes_remaining:
            self.skipped.append(f"{name}: output byte limit exceeded")
            return False
        return True

    def record(self, name: str, size: int) -> bool:
        if size > self.bytes_remaining:
            self.skipped.append(f"{name}: output byte limit exceeded")
            return False
        self.files_remaining -= 1
        self.bytes_remaining -= size
        return True

    async def read(self, name: str, chunks: AsyncIterator[bytes]) -> bytes | None:
        """Buffer a streamed download, stopping as soon as it exceeds the remaining bytes."""
        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk)
            if len(buffer) > self.bytes_remaining:
                self.skipped.append(f"{name}: output byte limit exceeded")
                return None
        content = bytes(buffer)
        return content if self.record(name, len(content)) else None


def _declared_size(metadata: object, attribute: str) -> int | None:
    value = getattr(metadata, attribute, None)
    return value if isinstance(value, int) else None


async def capture_sandbox_files(
    provider_model: object,
    messages: Sequence[ModelMessage],
    *,
    excluded_hashes: Set[str] = frozenset(),
    excluded_provider_file_ids: Set[str] = frozenset(),
) -> tuple[list[CapturedSandboxFile], list[str]]:
    inline = _inline_files(messages)
    skipped: list[str] = []
    budget = _RetrievalBudget(
        files_remaining=max(0, settings.NATIVE_RUN_CODE_MAX_OUTPUT_FILES - len(inline)),
        bytes_remaining=max(
            0,
            settings.NATIVE_RUN_CODE_MAX_OUTPUT_BYTES - sum(len(item.content) for item in inline),
        ),
        skipped=skipped,
    )
    # Provider-named copies go first so hash dedup keeps the sandbox filename over a
    # synthetic inline name; the same bytes can arrive through both channels.
    captured: list[CapturedSandboxFile] = []
    try:
        if isinstance(provider_model, OpenAIResponsesModel):
            captured.extend(
                await _openai_container_files(
                    provider_model,
                    messages,
                    budget,
                    excluded_provider_file_ids=excluded_provider_file_ids,
                )
            )
        elif isinstance(provider_model, AnthropicModel):
            captured.extend(await _anthropic_output_files(provider_model, messages, budget))
    except Exception as exc:
        skipped.append(f"Provider output retrieval failed: {type(exc).__name__}")
    captured.extend(inline)
    deduped: list[CapturedSandboxFile] = []
    hashes: set[str] = set()
    total_bytes = 0
    for item in captured:
        digest = hashlib.sha256(item.content).hexdigest()
        if digest in excluded_hashes or digest in hashes:
            continue
        hashes.add(digest)
        if len(deduped) >= settings.NATIVE_RUN_CODE_MAX_OUTPUT_FILES:
            skipped.append(f"{item.name}: output file limit exceeded")
            continue
        if total_bytes + len(item.content) > settings.NATIVE_RUN_CODE_MAX_OUTPUT_BYTES:
            skipped.append(f"{item.name}: output byte limit exceeded")
            continue
        total_bytes += len(item.content)
        deduped.append(item)
    return deduped, skipped


def _inline_files(messages: Sequence[ModelMessage]) -> list[CapturedSandboxFile]:
    output: list[CapturedSandboxFile] = []
    index = 0
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if not isinstance(part, FilePart):
                continue
            index += 1
            extension = _extension_for_media_type(part.content.media_type)
            identifier = getattr(part.content, "identifier", None)
            name = (
                safe_sandbox_name(identifier)
                if isinstance(identifier, str) and PurePath(identifier).suffix
                else f"sandbox-output-{index}{extension}"
            )
            output.append(
                CapturedSandboxFile(
                    name=name,
                    content=part.content.data,
                    media_type=part.content.media_type,
                )
            )
    return output


async def _openai_container_files(
    model: OpenAIResponsesModel,
    messages: Sequence[ModelMessage],
    budget: _RetrievalBudget,
    *,
    excluded_provider_file_ids: Set[str] = frozenset(),
) -> list[CapturedSandboxFile]:
    container_ids = dict.fromkeys(
        args["container_id"]
        for args in (_part_args(part) for part in _native_calls(messages))
        if isinstance(args.get("container_id"), str)
    )
    output: list[CapturedSandboxFile] = []
    for container_id in container_ids:
        if budget.exhausted():
            break
        async for metadata in model.client.containers.files.list(container_id):
            if budget.exhausted():
                break
            if metadata.id in excluded_provider_file_ids:
                continue
            name = safe_sandbox_name(getattr(metadata, "path", None) or metadata.id)
            if not budget.admit(name, _declared_size(metadata, "bytes")):
                continue
            response = await model.client.containers.files.content.retrieve(
                metadata.id,
                container_id=container_id,
            )
            content = await budget.read(name, await response.aiter_bytes())
            if content is None:
                continue
            output.append(
                CapturedSandboxFile(
                    name=name,
                    content=content,
                    media_type=_media_type_for_name(name),
                )
            )
    return output


async def _anthropic_output_files(
    model: AnthropicModel,
    messages: Sequence[ModelMessage],
    budget: _RetrievalBudget,
) -> list[CapturedSandboxFile]:
    file_ids: dict[str, None] = {}
    for message in messages:
        for part in getattr(message, "parts", ()):
            if isinstance(part, NativeToolReturnPart) and part.tool_name == "code_execution":
                _collect_file_ids(part.content, file_ids)
    output: list[CapturedSandboxFile] = []
    for file_id in file_ids:
        if budget.exhausted():
            break
        metadata = await model.client.beta.files.retrieve_metadata(file_id)
        name = safe_sandbox_name(getattr(metadata, "filename", None) or file_id)
        if not budget.admit(name, _declared_size(metadata, "size_bytes")):
            continue
        response = await model.client.beta.files.download(file_id)
        content = await budget.read(name, response.iter_bytes())
        if content is None:
            continue
        output.append(
            CapturedSandboxFile(
                name=name,
                content=content,
                media_type=getattr(metadata, "mime_type", None) or _media_type_for_name(name),
            )
        )
    return output


def _native_calls(messages: Sequence[ModelMessage]) -> list[NativeToolCallPart]:
    return [
        part
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, NativeToolCallPart) and part.tool_name == "code_execution"
    ]


def _part_args(part: NativeToolCallPart) -> dict[str, Any]:
    return part.args if isinstance(part.args, dict) else {}


def _collect_file_ids(value: object, target: dict[str, None]) -> None:
    if isinstance(value, Mapping):
        file_id = value.get("file_id")
        if isinstance(file_id, str) and file_id:
            target.setdefault(file_id)
        for item in value.values():
            _collect_file_ids(item, target)
    elif isinstance(value, list):
        for item in value:
            _collect_file_ids(item, target)


async def persist_sandbox_outputs(
    deps: RuntimeDeps,
    *,
    task: str,
    captured: Sequence[CapturedSandboxFile],
    input_file_ids: Sequence[UUID],
    input_revision_ids: Sequence[UUID],
    edit_target: RunCodeEditTarget | None = None,
    folder: str | None = None,
) -> tuple[list[RunCodeStoredOutput], list[str]]:
    stored: list[RunCodeStoredOutput] = []
    skipped: list[str] = []
    output_folder = _OutputFolderResolver(requested_name=folder)
    remaining = captured
    if edit_target is not None:
        edit_output = _select_edited_sandbox_output(captured, edit_target)
        try:
            stored.append(
                await _persist_edited_sandbox_output(
                    deps,
                    task=task,
                    output=edit_output,
                    edit_target=edit_target,
                    input_file_ids=input_file_ids,
                    input_revision_ids=input_revision_ids,
                )
            )
        except (AppValidationError, UnicodeDecodeError, ValueError) as exc:
            raise ToolFailed(
                "The selected edited output could not be saved as a new revision: "
                f"{getattr(exc, 'message', str(exc))}"
            ) from exc
        except ConflictError as exc:
            raise ToolFailed(
                "The selected file changed while the sandbox was editing it. Run the edit again "
                "against the latest revision."
            ) from exc
        remaining = [item for item in captured if item is not edit_output]
    for item in remaining:
        try:
            stored.append(
                await _persist_sandbox_output(
                    deps,
                    task=task,
                    output=item,
                    input_file_ids=input_file_ids,
                    input_revision_ids=input_revision_ids,
                    output_folder=output_folder,
                )
            )
        except (AppValidationError, ConflictError, UnicodeDecodeError, ValueError) as exc:
            skipped.append(f"{item.name}: {getattr(exc, 'message', str(exc))}")
    return stored, skipped


def _select_edited_sandbox_output(
    captured: Sequence[CapturedSandboxFile],
    edit_target: RunCodeEditTarget,
) -> CapturedSandboxFile:
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


async def _persist_edited_sandbox_output(
    deps: RuntimeDeps,
    *,
    task: str,
    output: CapturedSandboxFile,
    edit_target: RunCodeEditTarget,
    input_file_ids: Sequence[UUID],
    input_revision_ids: Sequence[UUID],
) -> RunCodeStoredOutput:
    entry = contract_for_content_type(edit_target.media_type)
    maximum = min(max_size_bytes(entry), settings.MAX_FILE_SIZE_AGENT_FILE)
    if len(output.content) > maximum:
        raise AppValidationError(
            "Edited file exceeds its governed size limit",
            field="content",
            details={"size_bytes": len(output.content), "max_bytes": maximum},
        )
    result = await append_file_revision(
        deps.db,
        workspace=deps.workspace,
        file_id=edit_target.file_id,
        content=output.content,
        actor=FileRevisionActor(agent_id=deps.agent.id),
        revision_kind="edit",
        expected_current_revision_id=edit_target.revision_id,
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
            "source": "native_run_code",
            "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
            "input_file_ids": [str(value) for value in input_file_ids],
            "input_revision_ids": [str(value) for value in input_revision_ids],
        },
    )
    return RunCodeStoredOutput(
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
        sandbox_name=safe_sandbox_name(output.name),
    )


async def _persist_sandbox_output(
    deps: RuntimeDeps,
    *,
    task: str,
    output: CapturedSandboxFile,
    input_file_ids: Sequence[UUID],
    input_revision_ids: Sequence[UUID],
    output_folder: _OutputFolderResolver,
) -> RunCodeStoredOutput:
    name = safe_sandbox_name(output.name)
    extension = PurePath(name).suffix.lower()
    artifact_type = _ARTIFACT_TYPE_BY_EXTENSION.get(extension)
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
        return RunCodeStoredOutput(
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

    entry = contract_for_content_type(output.media_type)
    if extension not in entry.extensions:
        extension = entry.extensions[0]
        name = f"{PurePath(name).stem}{extension}"
    maximum = min(max_size_bytes(entry), settings.MAX_FILE_SIZE_AGENT_FILE)
    if len(output.content) > maximum:
        raise AppValidationError(
            "Generated file exceeds its governed size limit",
            field="content",
            details={"size_bytes": len(output.content), "max_bytes": maximum},
        )
    folder = await output_folder.get(deps)
    result = await create_file_with_revision(
        deps.db,
        workspace=deps.workspace,
        name=name,
        content=output.content,
        content_type=entry.content_type,
        extension=extension,
        actor=FileRevisionActor(agent_id=deps.agent.id),
        resolved_folder=folder,
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
        details={
            "filename": result.file.name,
            "size_bytes": result.bytes_written,
            "revision_kind": result.revision.revision_kind,
            "content_hash": result.revision.content_hash,
            "source": "native_run_code",
            "task_sha256": hashlib.sha256(task.encode()).hexdigest(),
            "input_file_ids": [str(value) for value in input_file_ids],
            "input_revision_ids": [str(value) for value in input_revision_ids],
            "folder_id": str(folder.id),
        },
    )
    return RunCodeStoredOutput(
        kind="file",
        name=result.file.name,
        size_bytes=result.bytes_written,
        media_type=result.file.content_type,
        reference=FileReference(
            entity_id=result.file.id,
            label=result.file.name,
            description=f"Generated file · {result.bytes_written:,} bytes",
        ),
        folder=RunCodeFolder(id=folder.id, name=folder.name),
    )


def truncate_run_code_output(value: str) -> str:
    maximum = settings.NATIVE_RUN_CODE_OUTPUT_MAX_CHARS
    if len(value) <= maximum:
        return value
    keep = max(0, maximum - len(_TRUNCATED_MARKER))
    return value[:keep] + _TRUNCATED_MARKER


def rewrite_sandbox_links(
    value: str,
    outputs: Sequence[RunCodeStoredOutput],
) -> str:
    """Replace provider-local markdown links with durable workspace entity links."""
    outputs_by_name = {output.sandbox_name or output.name: output for output in outputs}
    outputs_by_stem = {
        PurePath(output.name).stem: output for output in outputs if output.kind == "artifact"
    }

    def replace_link(match: re.Match[str]) -> str:
        label = match.group("label")
        target = unquote(match.group("target").split(":", 1)[1])
        target_name = PurePath(target).name
        output = outputs_by_name.get(target_name) or outputs_by_stem.get(PurePath(target_name).stem)
        if output is None:
            return f"{label} (sandbox output was not retained)"
        entity_id = output.reference.entity_id
        if output.kind == "artifact":
            return f"{label}(/artifacts/{entity_id})"
        return f"{label}(/files?fileId={entity_id})"

    return _SANDBOX_MARKDOWN_LINK.sub(replace_link, value)


def _media_type_for_name(name: str) -> str:
    guessed, _encoding = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def _extension_for_media_type(media_type: str) -> str:
    overrides = {
        "image/jpeg": ".jpg",
        "text/markdown": ".md",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }
    return overrides.get(media_type, mimetypes.guess_extension(media_type) or ".bin")
