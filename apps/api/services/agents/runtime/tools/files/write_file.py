# apps/api/services/agents/runtime/tools/files/write_file.py

"""Runtime tool for writing approved durable files."""

import logging
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import ApprovalRequired, ModelRetry, RunContext

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
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
from services.files import write_agent_file

logger = logging.getLogger(__name__)


class WriteFileOutput(BaseModel):
    name: str
    bytes_written: int
    file_id: UUID
    revision_id: UUID


@runtime_tool(
    name="write_file",
    provider="core",
    label="Save File",
    description=(
        "Create or edit a durable UTF-8 file in the workspace's document store. "
        "Use for data, notes, and working documents the workspace keeps for "
        "reference and later work; use create_artifact for reports and documents "
        "the user will view, revise, or share."
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
            ToolFieldPresentation(key="file_id", label="Existing File ID"),
            ToolFieldPresentation(
                key="expected_current_revision_id",
                label="Expected Revision ID",
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
    file_id: UUID | None = None,
    expected_current_revision_id: UUID | None = None,
    content_ref: str | None = None,
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
        result = await write_agent_file(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            name=name,
            content=content,
            file_id=file_id,
            expected_current_revision_id=expected_current_revision_id,
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
    return WriteFileOutput(
        name=result.file.name,
        file_id=result.file.id,
        revision_id=result.revision.id,
        bytes_written=result.bytes_written,
    )
