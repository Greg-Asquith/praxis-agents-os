# apps/api/services/agents/runtime/tools/documents/utils.py

"""Shared loading, worker calls, and saving for the document tools."""

from collections.abc import Callable, Sequence
from functools import cache, partial
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

import services.documents
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.files import File, FileRevision
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.contract import ToolFieldPresentation
from services.agents.runtime.tools.files.utils import current_file_revision
from services.documents.inputs import load_input_files
from services.documents.outputs import (
    EditTarget,
    OutputFolderResolver,
    StoredOutput,
    save_file_edit,
    save_new_file,
)
from services.documents.reading import MAX_IMAGE_BYTES
from services.documents.worker import DocumentWorkerResult, get_document_worker_pool
from services.files.contract import FILE_CONTRACT, FileCategory
from services.files.utils import file_revision_ref, normalize_required_text
from services.storage.factory import get_storage_provider
from services.storage.paths import safe_filename
from utils.content import ContentScope
from utils.validation import normalize_optional_text

OFFICE_EXTENSIONS = {".pptx": "pptx", ".xlsx": "xlsx", ".docx": "docx"}
_LEGACY_EXTENSIONS = frozenset({".ppt", ".xls", ".doc"})
_FORMAT_TOOLS = {"pptx": "read_presentation", "xlsx": "read_workbook", "docx": "read_word_document"}
# Admission and processing each have their own timeout in the worker pool.
DOCUMENT_TOOL_TIMEOUT = settings.DOCUMENT_TOOLS_TIMEOUT_SECONDS * 2 + 10.0
FILE_ARG_FIELD = ToolFieldPresentation(
    key="file_id",
    label="File",
    format="entity",
    editable=True,
    entity_kind="file",
)
# The base revision belongs to this File, so approvals can't retarget an edit.
EDITED_FILE_FIELD = ToolFieldPresentation(
    key="file_id", label="File", format="entity", entity_kind="file"
)
WARNINGS_FIELD = ToolFieldPresentation(key="warnings", label="Check", format="list")
CREATE_ARG_FIELDS = (
    ToolFieldPresentation(key="name", label="File Name", editable=True),
    ToolFieldPresentation(key="folder", label="Folder", editable=True, secondary=True),
    ToolFieldPresentation(
        key="template_file_id",
        label="Template",
        format="entity",
        entity_kind="file",
        secondary=True,
    ),
)
NAME_FIELD = Field(max_length=255, description="The new File's name.")
FOLDER_FIELD = Field(
    max_length=255, description="A folder name. Omit to use this conversation's folder."
)
MEDIA_TYPES = {
    OFFICE_EXTENSIONS[extension]: entry.content_type
    for entry in FILE_CONTRACT
    for extension in entry.extensions
    if extension in OFFICE_EXTENSIONS
}
_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg"})
_TEMPLATES = Path(services.documents.__file__).resolve().parent / "templates"


async def load_file(
    ctx: RunContext[RuntimeDeps], file_id: UUID | None, file_format: Callable[[File], str]
) -> tuple[File, FileRevision, str, bytes]:
    """Loads the visible current revision of a File, checks its format, then reads its bytes."""
    file, revision = await current_file_revision(ctx, file_id)
    document_format = file_format(file)
    return file, revision, document_format, await _load_bytes(revision)


async def read_office_file(
    ctx: RunContext[RuntimeDeps], file_id: FileReference, document_format: str, **args: Any
) -> dict[str, Any]:
    """Reads one page of an Office File, headed by the File and revision it came from."""
    file, revision, _, data = await load_file(
        ctx, internal_entity_id(file_id), partial(office_format, expected=document_format)
    )
    result = await run_worker(
        "read",
        document_format=document_format,
        data=data,
        args=read_args(file, revision, **args),
    )
    return file_result(file, revision, result.value)


async def _load_bytes(revision: FileRevision) -> bytes:
    if revision.size_bytes > settings.DOCUMENT_TOOLS_MAX_SOURCE_BYTES:
        limit_mb = settings.DOCUMENT_TOOLS_MAX_SOURCE_BYTES // (1024 * 1024)
        raise ModelRetry(f"The file is larger than the {limit_mb} MiB that document tools read.")
    return await get_storage_provider().get_object(file_revision_ref(revision))


def office_format(file: File, *, expected: str | None = None) -> str:
    """Returns the Office format of a File, or explains which tool reads it instead."""
    extension = (file.extension or "").lower()
    document_format = OFFICE_EXTENSIONS.get(extension)
    if extension in _LEGACY_EXTENSIONS:
        raise ModelRetry(
            f"Document tools read .pptx, .xlsx, and .docx files, not {extension}. "
            "Call read_file to read its text."
        )
    if document_format is None:
        raise ModelRetry(
            "Document tools read .pptx, .xlsx, and .docx files. Call read_file for other files."
        )
    if expected is not None and document_format != expected:
        raise ModelRetry(
            f"This is a .{document_format} file. Call {_FORMAT_TOOLS[document_format]}."
        )
    return document_format


async def run_worker(
    operation: str,
    *,
    document_format: str,
    data: bytes,
    args: dict[str, Any],
    attachments: Sequence[bytes] = (),
) -> DocumentWorkerResult:
    """Runs a document worker operation and turns refusals into model-visible retries."""
    try:
        return await get_document_worker_pool().run(
            operation,
            document_format=document_format,
            data=data,
            args=args,
            attachments=attachments,
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc


def read_args(file: File, revision: FileRevision, **args: Any) -> dict[str, Any]:
    """Returns worker read arguments with the page budget and the text provenance."""
    return {
        **{key: value for key, value in args.items() if value is not None},
        "max_chars": settings.DOCUMENT_TOOLS_READ_MAX_CHARS,
        "source_ref": source_ref(file, revision),
    }


def source_ref(file: File, revision: FileRevision) -> str:
    """Returns the provenance attached to text read from a File revision."""
    return f"file:{file.id}/revision:{revision.id}"


def file_result(file: File, revision: FileRevision, value: dict[str, Any]) -> dict[str, Any]:
    """Returns a read result headed by the File and the revision it came from."""
    # A framed name taints Code Mode even when a page holds only numbers and plain names.
    name = {
        "node": "praxis_untrusted",
        "source_kind": "file",
        "source_ref": source_ref(file, revision),
        "content": file.name,
    }
    return {"file_id": str(file.id), "revision_id": str(revision.id), "name": name, **value}


async def edit_office_file(
    ctx: RunContext[RuntimeDeps],
    *,
    tool_name: str,
    document_format: str,
    file_id: FileReference,
    base_revision_id: UUID,
    operations: Sequence[BaseModel],
) -> dict[str, Any]:
    """Applies operations to a File's current revision and saves the result as its next revision.

    Nothing is saved when the base revision is stale or any operation fails.
    """
    file, revision = await current_file_revision(ctx, internal_entity_id(file_id))
    if file.scope == ContentScope.PLATFORM:
        raise ModelRetry("Platform files are read-only. Make a workspace copy before editing.")
    office_format(file, expected=document_format)
    if revision.id != base_revision_id:
        raise ModelRetry(_stale(revision.id))
    data = await _load_bytes(revision)
    worker_operations, images = await _worker_operations(ctx, tool_name, operations)
    result = await run_worker(
        "edit",
        document_format=document_format,
        data=data,
        attachments=images,
        args=_edit_args(ctx, source_ref(file, revision), worker_operations),
    )
    output = _output(result)
    target = EditTarget(
        file_id=file.id, revision_id=revision.id, name=file.name, media_type=file.content_type
    )
    details = _audit_details(tool_name, operations, data, output)
    try:
        async with ctx.deps.db.begin_nested():
            stored = await save_file_edit(
                ctx.deps,
                target=target,
                content=output,
                details={**details, "base_revision_id": str(revision.id)},
            )
    except ConflictError as exc:
        raise ModelRetry(_stale(exc.details.get("current_revision_id"))) from exc
    except (AppValidationError, AuthorizationError, NotFoundError) as exc:
        raise ModelRetry(exc.message) from exc
    return {**_saved(stored), "base_revision_id": str(revision.id), **result.value}


async def create_office_file(
    ctx: RunContext[RuntimeDeps],
    *,
    tool_name: str,
    document_format: str,
    name: str,
    folder: str | None,
    template_file_id: FileReference | None,
    clear_template: bool,
    operations: Sequence[BaseModel],
) -> dict[str, Any]:
    """Builds a new File from a template File or the bundled default, then applies operations."""
    file_name = _file_name(name, document_format)
    details: dict[str, Any] = {}
    if template_file_id is None:
        data = _default_template(document_format)
        text_source = f"template:default.{document_format}"
    else:
        template, revision, _, data = await load_file(
            ctx,
            internal_entity_id(template_file_id),
            partial(office_format, expected=document_format),
        )
        text_source = source_ref(template, revision)
        details = {"template_file_id": str(template.id), "template_revision_id": str(revision.id)}
    worker_operations, images = await _worker_operations(ctx, tool_name, operations)
    result = await run_worker(
        "edit",
        document_format=document_format,
        data=data,
        attachments=images,
        args={**_edit_args(ctx, text_source, worker_operations), "clear": clear_template},
    )
    output = _output(result)
    try:
        async with ctx.deps.db.begin_nested():
            stored = await save_new_file(
                ctx.deps,
                name=file_name,
                content=output,
                media_type=MEDIA_TYPES[document_format],
                folder=OutputFolderResolver(requested_name=normalize_optional_text(folder)),
                details={**_audit_details(tool_name, operations, data, output), **details},
            )
    except (AppValidationError, AuthorizationError, ConflictError) as exc:
        raise ModelRetry(exc.message) from exc
    return {**_saved(stored), **result.value}


async def _worker_operations(
    ctx: RunContext[RuntimeDeps], tool_name: str, operations: Sequence[BaseModel]
) -> tuple[list[dict[str, Any]], list[bytes]]:
    """Returns worker JSON operations, with image File references as attachment positions."""
    references = [
        reference
        for operation in operations
        if (reference := getattr(operation, "image_file_id", None)) is not None
    ]
    images = await load_input_files(
        ctx,
        references,
        tool_name=tool_name,
        categories={FileCategory.IMAGE},
        media_types=_IMAGE_MEDIA_TYPES,
        max_file_bytes=MAX_IMAGE_BYTES,
        max_total_bytes=settings.DOCUMENT_TOOLS_MAX_SOURCE_BYTES,
    )
    positions = {image.file_id: index for index, image in enumerate(images)}
    worker_operations = []
    for operation in operations:
        item = operation.model_dump(mode="json", exclude_none=True)
        reference = getattr(operation, "image_file_id", None)
        if reference is not None:
            del item["image_file_id"]
            item["image"] = positions[reference.entity_id]
        worker_operations.append(item)
    return worker_operations, [image.content for image in images]


def _edit_args(
    ctx: RunContext[RuntimeDeps], text_source: str, operations: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "operations": operations,
        "max_chars": settings.DOCUMENT_TOOLS_READ_MAX_CHARS,
        "source_ref": text_source,
        "author": ctx.deps.agent.name,
        "max_cells": settings.DOCUMENT_TOOLS_EDIT_MAX_CELLS,
    }


def _output(result: DocumentWorkerResult) -> bytes:
    if result.data is None:
        raise ModelRetry("The edit produced no file. Nothing was saved.")
    return result.data


def _audit_details(
    tool_name: str, operations: Sequence[BaseModel], source: bytes, output: bytes
) -> dict[str, Any]:
    return {
        "source": "document_tools",
        "tool": tool_name,
        "operation_count": len(operations),
        "source_bytes": len(source),
        "output_bytes": len(output),
    }


def _saved(stored: StoredOutput) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file_id": str(stored.reference.entity_id),
        "name": stored.name,
        "revision_id": str(stored.revision_id),
        "revision_number": stored.revision_number,
        "reference": stored.reference.model_dump(mode="json"),
    }
    if stored.folder is not None:
        result["folder"] = stored.folder.model_dump(mode="json")
    return result


def _stale(current_revision_id: object) -> str:
    return (
        "The file changed after you read it, so nothing was saved. Its current revision is "
        f"{current_revision_id}. Read it again and redo the edit with that base_revision_id."
    )


def _file_name(name: str, document_format: str) -> str:
    file_name = safe_filename(name, fallback="")
    if not file_name:
        raise ModelRetry("name is required.")
    extension = f".{document_format}"
    if not file_name.lower().endswith(extension):
        file_name = f"{file_name}{extension}"
    try:
        return normalize_required_text(file_name)
    except AppValidationError:
        raise ModelRetry(
            f"name is too long. With its {extension} extension it must be at most 255 characters."
        ) from None


@cache
def _default_template(document_format: str) -> bytes:
    return (_TEMPLATES / f"default.{document_format}").read_bytes()
