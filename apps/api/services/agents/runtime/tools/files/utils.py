# apps/api/services/agents/runtime/tools/files/utils.py

"""Shared helpers for runtime file tools."""

from uuid import UUID

from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import NotFoundError
from core.settings import settings
from models.files import File, FileRevision
from services.agents.models.registry import get_model
from services.agents.models.resolution import resolve_agent_model
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.untrusted import UntrustedNode
from services.files.utils import (
    conversation_file_revision_id,
    file_for_revision,
    get_visible_file,
    get_visible_file_revision,
)
from utils.content import ContentScope
from utils.text_window import TextWindowError, utf8_window


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
    """Loads a visible file revision, retaining the conversation pin."""
    if file_id is None:
        raise ModelRetry("file_id is required when reading a file.")
    try:
        file = await get_visible_file(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            file_id=file_id,
        )
        pin = None
        if file.scope == ContentScope.PLATFORM or file.is_tool_result:
            pin = await conversation_file_revision_id(
                ctx.deps.db,
                workspace_id=ctx.deps.workspace.id,
                conversation_id=ctx.deps.conversation.id,
                file_id=file.id,
            )
        revision = await get_visible_file_revision(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            file=file,
            revision_id=pin,
        )
        file = file_for_revision(file, revision)
    except NotFoundError as exc:
        raise ModelRetry("File not found.") from exc
    return file, revision


def slice_text(
    text: str,
    *,
    offset: int,
    max_bytes: int,
    metadata: dict[str, object],
) -> dict[str, object]:
    """Return a bounded UTF-8 text slice with continuation metadata."""
    try:
        window = utf8_window(text.encode("utf-8"), offset=offset, max_bytes=max_bytes)
    except TextWindowError as exc:
        raise ModelRetry(str(exc)) from None
    content, end, total = window.content, window.end_offset, window.total_bytes
    result: dict[str, object] = {
        **metadata,
        "mode": "content",
        "offset": offset,
        "end_offset": end,
        "total_bytes": total,
        "content": (
            UntrustedNode(
                source_kind="file",
                source_ref=f"file:{metadata['file_id']}/revision:{metadata['revision_id']}",
                content=content,
            ).model_dump(mode="json")
            if metadata.get("scope") == ContentScope.PLATFORM
            or metadata.get("source") == "tool_result"
            else content
        ),
    }
    if end < total:
        result["truncated"] = True
        result["hint"] = (
            f"Showing bytes {offset}-{end} of {total}; call read_file again with offset={end}."
        )
    else:
        result["truncated"] = False
    return result


def file_metadata(file: File, revision: FileRevision, *, source: str) -> dict[str, object]:
    """Return common metadata for file read outputs."""
    return {
        "kind": "file",
        "source": "tool_result" if file.is_tool_result else source,
        "scope": file.scope,
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
            "The content cannot be inspected until processing succeeds; use mode='url' only if "
            "the user requested the original file as a download."
        )
    return (
        "File processing is not ready yet. Retry content mode later; use mode='url' only if the "
        "user requested the original file as a download."
    )


def agent_model_supports_vision(deps: RuntimeDeps) -> bool:
    """Return whether the configured runtime model can receive image content."""
    resolved = resolve_agent_model(deps.agent)
    return get_model(resolved.provider, resolved.model).supports_vision
