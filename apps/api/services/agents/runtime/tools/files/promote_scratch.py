# apps/api/services/agents/runtime/tools/files/promote_scratch.py

"""Runtime tool for promoting scratch content to a durable file."""

from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_APPROVAL,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.files.utils import conversation_scope
from services.agents.runtime.tools.registry import runtime_tool
from services.files import write_agent_file
from services.scratch import delete_scratch_entry, read_scratch_entry


class PromoteScratchOutput(BaseModel):
    file_id: UUID
    revision_id: UUID
    name: str
    deleted_scratch: bool = True


@runtime_tool(
    name="promote_scratch",
    provider="core",
    label="Promote scratch",
    description="Promote one scratch entry to a durable editable file and delete the scratch entry.",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=30.0,
    output_model=PromoteScratchOutput,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="file-plus",
        running_label="Saving the Draft {scratch_name} as a File",
        completed_label="Saved {name} to Your Files",
        failed_label="Couldn't Save the Draft as a File",
        approval_title="Save a Draft to your Files",
        approval_prompt=(
            "The agent wants to save the draft {scratch_name} as a permanent file "
            "in your workspace."
        ),
        arg_fields=(
            ToolFieldPresentation(key="scratch_name", label="Draft"),
            ToolFieldPresentation(key="file_name", label="Save as"),
        ),
    ),
)
async def promote_scratch(
    ctx: RunContext[RuntimeDeps],
    scratch_name: str,
    file_name: str | None = None,
) -> PromoteScratchOutput:
    """Create a durable file from scratch content and delete the scratch entry."""
    scope = conversation_scope(ctx)
    try:
        entry = await read_scratch_entry(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            scope=scope,
            name=scratch_name,
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc
    if entry is None:
        raise ModelRetry(f"Scratch entry {scratch_name!r} was not found.")

    target_name = file_name or f"{entry.name}.md"
    try:
        result = await write_agent_file(
            ctx.deps.db,
            workspace=ctx.deps.workspace,
            agent=ctx.deps.agent,
            name=target_name,
            content=entry.content,
            reject_existing_name=True,
        )
        deleted = await delete_scratch_entry(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            scope=scope,
            name=entry.name,
        )
    except (AppValidationError, ConflictError, NotFoundError) as exc:
        raise ModelRetry(str(exc)) from exc

    return PromoteScratchOutput(
        file_id=result.file.id,
        revision_id=result.revision.id,
        name=result.file.name,
        deleted_scratch=deleted,
    )
