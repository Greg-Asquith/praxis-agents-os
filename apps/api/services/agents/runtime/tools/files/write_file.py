# apps/api/services/agents/runtime/tools/files/write_file.py

"""Runtime tool for writing approved durable files."""

import logging
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ApprovalRequired, ModelRetry, RunContext

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference, internal_entity_id
from services.agents.runtime.staged_tool_content import (
    delete_staged_write_content,
    resolve_staged_write_content,
)
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files import (
    create_conversation_file_references,
    resolve_folder_by_name,
    write_agent_file,
)
from utils.validation import normalize_optional_text

logger = logging.getLogger(__name__)


class WriteFileOutput(BaseModel):
    name: str
    bytes_written: int
    file_id: UUID
    revision_id: UUID
    reference: FileReference


@runtime_tool(
    name="write_file",
    provider="core",
    label="Save File",
    code_eligible=True,
    description=(
        "Create or edit a durable UTF-8 file in the workspace's document store. "
        "Use for data, notes, and working documents the workspace keeps for "
        "reference and later work; use create_artifact for reports and documents "
        "the user will view, revise, or share. New files can be placed in a named "
        "folder; existing-file edits keep their current folder."
    ),
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=30.0,
    output_model=WriteFileOutput,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file-plus",
        running_label="Saving {name}",
        completed_label="Saved {name}",
        failed_label="Couldn't Save {name}",
        approval_title="Save a File",
        approval_prompt=(
            "The agent wants to create or update {name} in your workspace files. "
            "Review the target and content details before approving."
        ),
        approve_label="Approve & Save",
        arg_fields=(
            ToolFieldPresentation(
                key="name",
                label="File Name",
                editable=True,
                placeholder="Name this file",
            ),
            ToolFieldPresentation(
                key="folder",
                label="Folder",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="file_id",
                label="Existing File",
                format="entity",
                editable=True,
                secondary=True,
                entity_kind="file",
            ),
            ToolFieldPresentation(key="content", label="Content", format="multiline"),
        ),
        result_fields=(
            ToolFieldPresentation(key="name", label="File"),
            ToolFieldPresentation(key="bytes_written", label="Size", format="bytes"),
        ),
    ),
)
async def write_file(
    ctx: RunContext[RuntimeDeps],
    name: str,
    content: str | None = None,
    file_id: FileReference | None = None,
    expected_current_revision_id: UUID | None = None,
    content_ref: str | None = None,
    folder: Annotated[
        str | None,
        Field(
            max_length=255,
            description=(
                "Optional folder name for a newly created file. The folder is created if needed; "
                "existing-file edits ignore this value."
            ),
        ),
    ] = None,
) -> WriteFileOutput:
    """Write approved durable file content."""
    if content is not None and content_ref is not None:
        raise ModelRetry("Provide content or content_ref, not both.")
    if not ctx.tool_call_approved:
        if content_ref is not None:
            raise ModelRetry("content_ref can only be used for approved write_file replays.")
        if content is None:
            raise ModelRetry("content is required when writing a durable file.")
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > settings.MAX_FILE_SIZE_AGENT_FILE:
            raise ModelRetry(
                f"Durable file content cannot exceed {settings.MAX_FILE_SIZE_AGENT_FILE} bytes."
            )
        raise ApprovalRequired(
            metadata={
                "name": name,
                "bytes": content_bytes,
            }
        )
    if content_ref is not None:
        try:
            content = await resolve_staged_write_content(
                workspace_id=ctx.deps.workspace.id,
                run_id=ctx.deps.run.id,
                content_ref=content_ref,
            )
        except AppValidationError as exc:
            raise ModelRetry(exc.message) from exc
    if content is None:
        raise ModelRetry("content is required when writing a durable file.")
    try:
        internal_file_id = internal_entity_id(file_id) if file_id is not None else None
        normalized_folder = normalize_optional_text(folder)
        async with ctx.deps.db.begin_nested():
            target_folder = (
                await resolve_folder_by_name(
                    ctx.deps.db,
                    workspace=ctx.deps.workspace,
                    agent=ctx.deps.agent,
                    requested_by=ctx.deps.user,
                    name=normalized_folder,
                )
                if internal_file_id is None and normalized_folder is not None
                else None
            )
            result = await write_agent_file(
                ctx.deps.db,
                workspace=ctx.deps.workspace,
                agent=ctx.deps.agent,
                name=name,
                content=content,
                file_id=internal_file_id,
                expected_current_revision_id=expected_current_revision_id,
                folder_id=target_folder.id if target_folder is not None else None,
            )
    except (AppValidationError, ConflictError, NotFoundError) as exc:
        raise ModelRetry(str(exc)) from exc
    if content_ref is not None:
        try:
            await delete_staged_write_content(
                workspace_id=ctx.deps.workspace.id,
                run_id=ctx.deps.run.id,
                content_ref=content_ref,
            )
        except Exception:
            logger.warning(
                "Failed to delete staged write_file content after durable write",
                extra={"run_id": str(ctx.deps.run.id), "file_id": str(result.file.id)},
                exc_info=True,
            )
    if internal_file_id is None:
        await create_conversation_file_references(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            conversation_id=ctx.deps.conversation.id,
            file_ids=[result.file.id],
            created_by_user_id=ctx.deps.user.id,
        )
    return WriteFileOutput(
        name=result.file.name,
        file_id=result.file.id,
        revision_id=result.revision.id,
        reference=FileReference(
            entity_id=result.file.id,
            label=result.file.name,
            description=f"{result.file.category.title()} · {result.file.size_bytes:,} bytes",
        ),
        bytes_written=result.bytes_written,
    )
