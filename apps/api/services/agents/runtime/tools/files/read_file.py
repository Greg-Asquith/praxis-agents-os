# apps/api/services/agents/runtime/tools/files/read_file.py

"""Runtime tool for reading workspace files and scratch entries."""

from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic_ai import ModelRetry, RunContext, ToolReturn
from pydantic_ai.messages import BinaryContent

from core.exceptions.general import AppValidationError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import TOOL_EFFECT_READ
from services.agents.runtime.tools.files.utils import (
    agent_model_supports_vision,
    content_limit,
    conversation_scope,
    current_file_revision,
    file_metadata,
    processing_guidance,
    slice_text,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files.contract import FileCategory
from services.files.utils import private_ref_from_key
from services.scratch import read_scratch_entry
from services.storage.factory import get_storage_provider


@runtime_tool(
    name="read_file",
    provider="core",
    label="Read file",
    description="Read a workspace file by id or a scratch entry by name in content or signed-url mode.",
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=30.0,
    configurable=False,
    auto_mount=True,
)
async def read_file(
    ctx: RunContext[RuntimeDeps],
    file_id: UUID | None = None,
    scratch_name: str | None = None,
    mode: Literal["content", "url"] = "content",
    offset: int = 0,
    max_bytes: int | None = None,
):
    """Read file content, file signed URLs, or scratch content."""
    if (file_id is None) == (scratch_name is None):
        raise ModelRetry("Provide exactly one of file_id or scratch_name.")
    if offset < 0:
        raise ModelRetry("offset must be greater than or equal to 0.")
    normalized_limit = content_limit(max_bytes)

    if scratch_name is not None:
        if mode != "content":
            raise ModelRetry("Scratch entries can only be read with mode='content'.")
        try:
            entry = await read_scratch_entry(
                ctx.deps.db,
                workspace_id=ctx.deps.workspace.id,
                scope=conversation_scope(ctx),
                name=scratch_name,
            )
        except AppValidationError as exc:
            raise ModelRetry(exc.message) from exc
        if entry is None:
            raise ModelRetry(f"Scratch entry {scratch_name!r} was not found.")
        return slice_text(
            entry.content,
            offset=offset,
            max_bytes=normalized_limit,
            metadata={
                "kind": "scratch",
                "name": entry.name,
                "expires_at": entry.expires_at.isoformat(),
            },
        )

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
            "mode": "url",
            "file_id": str(file.id),
            "name": file.name,
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
            raise ModelRetry("This agent model cannot inspect image bytes. Use mode='url'.")
        data = await get_storage_provider().get_object(private_ref_from_key(revision.object_key))
        metadata = file_metadata(file, revision, source="image")
        return ToolReturn(
            return_value=metadata,
            content=[
                BinaryContent(
                    data=data,
                    media_type=file.content_type,
                    identifier=str(file.id),
                )
            ],
            metadata={"file_id": str(file.id), "revision_id": str(revision.id)},
        )

    raise ModelRetry("This file type is only available through mode='url'.")
