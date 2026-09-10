# apps/api/services/agents/runtime/tools/files/read_file.py

"""Runtime tool for reading workspace files."""

import asyncio
from datetime import timedelta
from typing import Literal

from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.messages import BinaryContent

from core.settings import settings
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


@runtime_tool(
    name="read_file",
    provider="core",
    label="Read File",
    code_eligible=True,
    description=(
        "Inspect a workspace or published platform file by id. "
        "Use content mode for inspection; use url mode only when the user needs a download."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=settings.CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS + 5.0,
    configurable=False,
    auto_mount=True,
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
    normalized_limit = content_limit(max_bytes)

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
        return slice_text(
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
                f"{message} You can still pass this file id to run_code to work with the "
                "original bytes."
            ) from exc
        return slice_text(
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

    raise ModelRetry(
        "This file type cannot be inspected as content. "
        "Use mode='url' only if the user requested a download."
    )
