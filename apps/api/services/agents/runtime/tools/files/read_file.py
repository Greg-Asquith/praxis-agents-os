# apps/api/services/agents/runtime/tools/files/read_file.py

"""Runtime tool for reading workspace files."""

import asyncio
from datetime import timedelta
from typing import Literal

from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.messages import BinaryContent

from core.settings import settings
from services.agents.runtime.code_mode.metadata import called_from_script
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.files.utils import (
    agent_model_supports_vision,
    content_limit,
    current_file_revision,
    file_metadata,
    processing_guidance,
    slice_text,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files.attachment_text import markdown_for_revision
from services.files.contract import FileCategory
from services.files.utils import file_revision_ref
from services.storage.factory import get_storage_provider
from utils.document_markdown import DocumentConversionError

# The transcript copy of a script's read: one normal window plus headroom for escaping.
_MAX_PUBLIC_RESULT_CHARS = 6 * settings.READ_FILE_MAX_CONTENT_BYTES + 64_000


@runtime_tool(
    name="read_file",
    defer_loading=False,
    provider="core",
    label="Read File",
    code_eligible=True,
    description=(
        "Inspect a workspace or published platform file by id. "
        "Use content mode for inspection; use url mode only when the user needs a download. "
        f"Content mode reads {settings.READ_FILE_MAX_CONTENT_BYTES:,} bytes at a time; in "
        "run_code a script reads up to the sandbox value limit per call."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=settings.CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS + 5.0,
    configurable=False,
    auto_mount=True,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading a File",
        completed_label="Read a File",
        failed_label="Couldn't Read the File",
        arg_fields=(
            ToolFieldPresentation(
                key="file_id",
                label="File",
                format="entity",
                editable=True,
                entity_kind="file",
            ),
            ToolFieldPresentation(key="mode", label="Read As", secondary=True),
        ),
    ),
)
async def read_file(
    ctx: RunContext[RuntimeDeps],
    file_id: FileReference,
    mode: Literal["content", "url"] = "content",
    offset: int = 0,
    max_bytes: int | None = None,
):
    """Read file content or a signed download URL."""
    if offset < 0:
        raise ModelRetry("offset must be greater than or equal to 0.")
    in_script = called_from_script(ctx)
    normalized_limit = content_limit(max_bytes, in_script=in_script)

    file, revision = await current_file_revision(ctx, internal_entity_id(file_id))
    if mode == "url":
        download = await get_storage_provider().create_signed_download(
            file_revision_ref(revision),
            expires_in=timedelta(minutes=10),
            force_download=True,
            filename=file.name,
        )
        return {
            **file_metadata(file, revision, source="url"),
            "mode": "url",
            "url": download.url,
            "expires_at": download.expires_at.isoformat(),
            "note": "Share this link with the user only when they need direct download access; it expires.",
        }

    if file.category == FileCategory.EDITABLE_TEXT.value:
        data = await get_storage_provider().get_object(file_revision_ref(revision))
        return _text_window(
            data.decode("utf-8", errors="replace"),
            offset=offset,
            max_bytes=normalized_limit,
            metadata=file_metadata(file, revision, source="content"),
        )

    if file.category == FileCategory.INGESTIBLE_DOCUMENT.value:
        source = "markdown" if revision.markdown_object_key else "markdown-on-demand"
        try:
            markdown = await asyncio.wait_for(
                markdown_for_revision(
                    file,
                    revision,
                    max_bytes=settings.FILES_MAX_MARKDOWN_BYTES,
                ),
                timeout=settings.CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS,
            )
        except (TimeoutError, DocumentConversionError) as exc:
            if file.processing_status == "error":
                message = processing_guidance(file)
            else:
                message = "The document couldn't be read."
            raise ModelRetry(
                f"{message} For a .pptx, .xlsx, or .docx file, pass this file id to "
                "read_presentation, read_workbook, or read_word_document instead."
            ) from exc
        return _text_window(
            markdown,
            offset=offset,
            max_bytes=normalized_limit,
            metadata=file_metadata(file, revision, source=source),
        )

    if file.category == FileCategory.IMAGE.value:
        if not agent_model_supports_vision(ctx.deps):
            raise ModelRetry(
                "The configured model does not support image inspection. "
                "Use mode='url' only if the user requested a download; a URL will not let this "
                "model inspect the image."
            )
        data = await get_storage_provider().get_object(file_revision_ref(revision))
        metadata = file_metadata(file, revision, source="image")
        return ToolReturn(
            return_value=[
                metadata,
                BinaryContent(
                    data=data,
                    media_type=file.content_type,
                    identifier=str(file.id),
                ),
            ],
            metadata={"file_id": str(file.id), "revision_id": str(revision.id)},
        )

    if file.category in {FileCategory.VIDEO.value, FileCategory.AUDIO.value}:
        kind = file.category
        if file.processing_status == "error":
            message = f"The {kind} couldn't be prepared: {file.processing_error}"
        elif file.processing_status in ("pending", "processing"):
            message = f"The {kind} is still being prepared. Its duration isn't known yet."
        elif kind == FileCategory.AUDIO.value:
            message = "Audio can't be read as text. Pass the file id to cut_video_clips as music."
        else:
            message = "Video can't be read as text. Pass the file id to the video tools."
        return {
            **file_metadata(file, revision, source=kind),
            "status": file.processing_status,
            "message": message,
        }

    raise ModelRetry(
        "This file type cannot be inspected as content. "
        "Use mode='url' only if the user requested a download."
    )


def _text_window(
    text: str, *, offset: int, max_bytes: int, metadata: dict[str, object]
) -> dict[str, object] | ToolReturn:
    shown = slice_text(
        text,
        offset=offset,
        max_bytes=min(max_bytes, settings.READ_FILE_MAX_CONTENT_BYTES),
        metadata=metadata,
    )
    if max_bytes <= settings.READ_FILE_MAX_CONTENT_BYTES or not shown["truncated"]:
        return shown
    # A script reads the larger window; the transcript keeps one normal window.
    window = slice_text(text, offset=offset, max_bytes=max_bytes, metadata=metadata)
    return ToolReturn(return_value=window, metadata={"public_result": shown})
