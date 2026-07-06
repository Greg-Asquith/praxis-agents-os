# apps/api/services/agents/runtime/tools/files/write_file.py

"""Runtime tool for writing scratch entries and approved durable files."""

import logging
from typing import Literal
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
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
)
from services.agents.runtime.tools.files.utils import conversation_scope
from services.agents.runtime.tools.registry import runtime_tool
from services.files import write_agent_file
from services.scratch import upsert_scratch_entry

logger = logging.getLogger(__name__)


class WriteFileOutput(BaseModel):
    destination: Literal["scratch", "file"]
    name: str
    bytes_written: int
    file_id: UUID | None = None
    revision_id: UUID | None = None
    expires_at: str | None = None


@runtime_tool(
    name="write_file",
    provider="core",
    label="Write file",
    description="Write UTF-8 text to scratch automatically, or create/edit a durable file after approval.",
    effect=TOOL_EFFECT_WRITE,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=True,
    takes_ctx=True,
    timeout=30.0,
    output_model=WriteFileOutput,
    configurable=False,
    auto_mount=True,
)
async def write_file(
    ctx: RunContext[RuntimeDeps],
    name: str,
    content: str | None = None,
    destination: Literal["scratch", "file"] = "scratch",
    file_id: UUID | None = None,
    expected_current_revision_id: UUID | None = None,
    content_ref: str | None = None,
) -> WriteFileOutput:
    """Write scratch or approved durable file content."""
    if destination == "scratch":
        if content_ref is not None:
            raise ModelRetry("content_ref is only used for approved durable file writes.")
        if content is None:
            raise ModelRetry("content is required when writing scratch.")
        try:
            entry = await upsert_scratch_entry(
                ctx.deps.db,
                workspace_id=ctx.deps.workspace.id,
                scope=conversation_scope(ctx),
                name=name,
                content=content,
                created_by_run_id=ctx.deps.run.id,
            )
        except AppValidationError as exc:
            raise ModelRetry(exc.message) from exc
        return WriteFileOutput(
            destination="scratch",
            name=entry.name,
            bytes_written=entry.content_bytes,
            expires_at=entry.expires_at.isoformat(),
        )

    if destination != "file":
        raise ModelRetry("destination must be either 'scratch' or 'file'.")
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
                "destination": "file",
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
        destination="file",
        name=result.file.name,
        file_id=result.file.id,
        revision_id=result.revision.id,
        bytes_written=result.bytes_written,
    )
