# apps/api/services/agents/runtime/tools/files/list_files.py

"""Runtime tool for listing workspace files."""

from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import FileReference
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.files import list_files as list_workspace_files


class RuntimeFileSummary(BaseModel):
    id: UUID
    name: str
    category: str
    media_type: str
    size_bytes: int
    processing_status: str
    updated_at: str
    reference: FileReference


class ListFilesOutput(BaseModel):
    files: list[RuntimeFileSummary]
    total: int


@runtime_tool(
    name="list_files",
    provider="core",
    label="List Files",
    description="List workspace files readable by the current agent.",
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=10.0,
    output_model=ListFilesOutput,
    configurable=False,
    auto_mount=True,
    presentation=ToolPresentation(
        icon="files",
        running_label="Looking Through Files",
        completed_label="Found {total} Files",
        failed_label="Couldn't Look Through Files",
        arg_fields=(
            ToolFieldPresentation(
                key="name_contains",
                label="Matching",
                secondary=True,
            ),
        ),
    ),
)
async def list_files(
    ctx: RunContext[RuntimeDeps],
    name_contains: str | None = None,
    limit: int = 25,
) -> ListFilesOutput:
    """List files available to the current agent run."""
    if limit < 1 or limit > 100:
        raise ModelRetry("limit must be between 1 and 100.")
    response = await list_workspace_files(
        ctx.deps.db,
        workspace=ctx.deps.workspace,
        search=name_contains,
        limit=limit,
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
                reference=FileReference(
                    entity_id=file.id,
                    label=file.name,
                    description=f"{file.category.title()} · {file.size_bytes:,} bytes",
                ),
            )
            for file in response.files
        ],
        total=response.total,
    )
