# apps/api/services/agents/runtime/tools/files/utils.py

"""Shared helpers for runtime file and scratch tools."""

from uuid import UUID

from pydantic_ai import ModelRetry, RunContext
from sqlalchemy import select

from core.exceptions.general import NotFoundError
from core.settings import settings
from models.files import File, FileRevision
from services.agents.models.registry import get_model
from services.agents.models.resolution import resolve_agent_model
from services.agents.runtime.context import RuntimeDeps
from services.files.utils import get_file_for_workspace
from services.scratch.domain import ScratchScope


def conversation_scope(ctx: RunContext[RuntimeDeps]) -> ScratchScope:
    """Return the scratch scope for the current conversation."""
    return ScratchScope(conversation_id=ctx.deps.conversation.id)


def content_limit(max_bytes: int | None) -> int:
    """Validate and normalize a read content byte limit."""
    if max_bytes is None:
        return settings.READ_FILE_MAX_CONTENT_BYTES
    if max_bytes < 1:
        raise ModelRetry("max_bytes must be greater than 0.")
    if max_bytes > settings.READ_FILE_MAX_CONTENT_BYTES:
        raise ModelRetry(
            f"max_bytes cannot exceed {settings.READ_FILE_MAX_CONTENT_BYTES}; use offset to continue."
        )
    return max_bytes


async def current_file_revision(
    ctx: RunContext[RuntimeDeps],
    file_id: UUID | None,
) -> tuple[File, FileRevision]:
    """Load a workspace file and its current revision for a runtime read."""
    if file_id is None:
        raise ModelRetry("file_id is required when reading a workspace file.")
    try:
        file = await get_file_for_workspace(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            file_id=file_id,
        )
    except NotFoundError as exc:
        raise ModelRetry("File not found.") from exc
    if file.current_revision_id is None:
        raise ModelRetry("File has no current revision.")
    revision = await ctx.deps.db.scalar(
        select(FileRevision).where(
            FileRevision.id == file.current_revision_id,
            FileRevision.file_id == file.id,
            FileRevision.workspace_id == ctx.deps.workspace.id,
        )
    )
    if revision is None:
        raise ModelRetry("File revision not found.")
    return file, revision


def slice_text(
    text: str,
    *,
    offset: int,
    max_bytes: int,
    metadata: dict[str, object],
) -> dict[str, object]:
    """Return a bounded UTF-8 text slice with continuation metadata."""
    data = text.encode("utf-8")
    total = len(data)
    if offset > total:
        raise ModelRetry(f"offset is beyond the content length ({total} bytes).")
    if not _is_utf8_boundary(data, offset):
        raise ModelRetry("offset must be a UTF-8 character boundary; use a prior end_offset.")

    end = _previous_utf8_boundary(data, min(offset + max_bytes, total), lower_bound=offset)
    if end == offset and offset < total:
        width = _next_utf8_char_width(data[offset])
        raise ModelRetry(
            f"max_bytes is too small to include the next UTF-8 character; use at least {width}."
        )

    content = data[offset:end].decode("utf-8")
    result: dict[str, object] = {
        **metadata,
        "mode": "content",
        "offset": offset,
        "end_offset": end,
        "total_bytes": total,
        "content": content,
    }
    if end < total:
        result["truncated"] = True
        result["hint"] = (
            f"Showing bytes {offset}-{end} of {total}; call read_file again with offset={end}."
        )
    else:
        result["truncated"] = False
    return result


def _is_utf8_boundary(data: bytes, index: int) -> bool:
    return index == 0 or index == len(data) or (data[index] & 0b1100_0000) != 0b1000_0000


def _previous_utf8_boundary(data: bytes, index: int, *, lower_bound: int) -> int:
    while index > lower_bound and not _is_utf8_boundary(data, index):
        index -= 1
    return index


def _next_utf8_char_width(first_byte: int) -> int:
    if first_byte < 0b1000_0000:
        return 1
    if first_byte & 0b1110_0000 == 0b1100_0000:
        return 2
    if first_byte & 0b1111_0000 == 0b1110_0000:
        return 3
    if first_byte & 0b1111_1000 == 0b1111_0000:
        return 4
    return 1


def file_metadata(file: File, revision: FileRevision, *, source: str) -> dict[str, object]:
    """Return common metadata for file read outputs."""
    return {
        "kind": "file",
        "source": source,
        "file_id": str(file.id),
        "revision_id": str(revision.id),
        "name": file.name,
        "category": file.category,
        "media_type": file.content_type,
        "processing_status": file.processing_status,
    }


def processing_guidance(file: File) -> str:
    """Return model-facing guidance for an ingestible document that is not readable yet."""
    if file.processing_status == "error":
        return (
            f"File processing failed: {file.processing_error or 'no details available'}. "
            "Use mode='url' if the user needs the original file."
        )
    return "File processing is not ready yet. Retry later, or use mode='url' for the original file."


def agent_model_supports_vision(deps: RuntimeDeps) -> bool:
    """Return whether the configured runtime model can receive image content."""
    resolved = resolve_agent_model(deps.agent)
    return get_model(resolved.provider, resolved.model).supports_vision
