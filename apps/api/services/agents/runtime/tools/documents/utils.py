# apps/api/services/agents/runtime/tools/documents/utils.py

"""Shared loading and worker calls for the document read tools."""

from typing import Any
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import File, FileRevision
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import ToolFieldPresentation
from services.agents.runtime.tools.files.utils import current_file_revision
from services.documents.worker import DocumentWorkerResult, get_document_worker_pool
from services.files.utils import file_revision_ref
from services.storage.factory import get_storage_provider

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


async def load_file(
    ctx: RunContext[RuntimeDeps], file_id: UUID | None
) -> tuple[File, FileRevision, bytes]:
    """Loads the visible current revision of a File and its bytes."""
    file, revision = await current_file_revision(ctx, file_id)
    if revision.size_bytes > settings.DOCUMENT_TOOLS_MAX_SOURCE_BYTES:
        limit_mb = settings.DOCUMENT_TOOLS_MAX_SOURCE_BYTES // (1024 * 1024)
        raise ModelRetry(f"The file is larger than the {limit_mb} MiB that document tools read.")
    data = await get_storage_provider().get_object(file_revision_ref(revision))
    return file, revision, data


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
) -> DocumentWorkerResult:
    """Runs a document worker operation and turns refusals into model-visible retries."""
    try:
        return await get_document_worker_pool().run(
            operation, document_format=document_format, data=data, args=args
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
    return {"file_id": str(file.id), "revision_id": str(revision.id), "name": file.name, **value}
