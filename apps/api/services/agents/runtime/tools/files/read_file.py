# apps/api/services/agents/runtime/tools/files/read_file.py

"""Runtime tool for reading workspace files."""

from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.messages import BinaryContent

from services.agents.runtime.context import RuntimeDeps
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
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider


@runtime_tool(
    name="read_file",
    provider="core",
    label="Read File",
    description=(
        "Inspect a workspace file by id. "
        "Use content mode for inspection; use url mode only when the user needs a download."
    ),
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=30.0,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file",
        running_label="Reading a File",
        completed_label="Read a File",
        failed_label="Couldn't Read the File",
        arg_fields=(ToolFieldPresentation(key="mode", label="Read As", secondary=True),),
    ),
)
async def read_file(
    ctx: RunContext[RuntimeDeps],
    file_id: UUID,
    mode: Literal["content", "url"] = "content",
    offset: int = 0,
    max_bytes: int | None = None,
):
    """Read file content or a signed download URL."""
    if offset < 0:
        raise ModelRetry("offset must be greater than or equal to 0.")
    normalized_limit = content_limit(max_bytes)

    file, revision = await current_file_revision(ctx, file_id)
    if mode == "url":
        provider = get_storage_provider()
        download = await provider.create_signed_download(
            private_ref_from_key(revision.object_key),
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
        data = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
        return slice_text(
            data.decode("utf-8", errors="replace"),
            offset=offset,
            max_bytes=normalized_limit,
            metadata=file_metadata(file, revision, source="content"),
        )

    if file.category == FileCategory.INGESTIBLE_DOCUMENT.value:
        if file.processing_status == "ready" and revision.markdown_object_key:
            data = await get_storage_provider().get_object(
                private_ref_from_key(revision.markdown_object_key)
            )
            return slice_text(
                data.decode("utf-8", errors="replace"),
                offset=offset,
                max_bytes=normalized_limit,
                metadata=file_metadata(file, revision, source="markdown"),
            )
        return {
            **file_metadata(file, revision, source="markdown"),
            "status": file.processing_status,
            "message": processing_guidance(file),
        }

    if file.category == FileCategory.IMAGE.value:
        if not agent_model_supports_vision(ctx.deps):
            raise ModelRetry(
                "The configured model does not support image inspection. "
                "Use mode='url' only if the user requested a download; a URL will not let this "
                "model inspect the image."
            )
        data = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
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
