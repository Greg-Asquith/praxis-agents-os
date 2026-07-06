# apps/api/services/agents/runtime/tools/files/list_files.py

"""Runtime tool for listing workspace files and scratch entries."""

from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import TOOL_EFFECT_READ
from services.agents.runtime.tools.files.utils import conversation_scope
from services.agents.runtime.tools.registry import runtime_tool
from services.files import list_files as list_workspace_files
from services.scratch import list_scratch_entries


class RuntimeFileSummary(BaseModel):
    id: UUID
    name: str
    category: str
    media_type: str
    size_bytes: int
    processing_status: str
    updated_at: str


class RuntimeScratchSummary(BaseModel):
    name: str
    content_bytes: int
    updated_at: str
    expires_at: str


class ListFilesOutput(BaseModel):
    files: list[RuntimeFileSummary]
    scratch: list[RuntimeScratchSummary]
    total: int


@runtime_tool(
    name="list_files",
    provider="core",
    label="List files",
    description="List workspace files and scratch entries readable in the current conversation.",
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=10.0,
    output_model=ListFilesOutput,
    configurable=False,
    auto_mount=True,
)
async def list_files(
    ctx: RunContext[RuntimeDeps],
    name_contains: str | None = None,
    limit: int = 25,
) -> ListFilesOutput:
    """List files and scratch entries available to the current agent run."""
    if limit < 1 or limit > 100:
        raise ModelRetry("limit must be between 1 and 100.")
    response = await list_workspace_files(
        ctx.deps.db,
        workspace=ctx.deps.workspace,
        search=name_contains,
        limit=limit,
    )
    scratch = await list_scratch_entries(
        ctx.deps.db,
        workspace_id=ctx.deps.workspace.id,
        scope=conversation_scope(ctx),
    )
    return ListFilesOutput(
        files=[
            RuntimeFileSummary(
                id=file.id,
                name=file.name,
                category=file.category,
                media_type=file.content_type,
                size_bytes=file.size_bytes,
                processing_status=file.processing_status,
                updated_at=file.updated_at.isoformat(),
            )
            for file in response.files
        ],
        scratch=[
            RuntimeScratchSummary(
                name=entry.name,
                content_bytes=entry.content_bytes,
                updated_at=entry.updated_at.isoformat(),
                expires_at=entry.expires_at.isoformat(),
            )
            for entry in scratch
        ],
        total=response.total,
    )
