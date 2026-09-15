# apps/api/integrations/sharepoint/tools/search_files.py

"""Searches items in the selected SharePoint libraries."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.search_items import search_items
from .schemas import SharePointSearchOutput
from .utils import (
    RESULTS_FIELD,
    SHAREPOINT_DRIVE_BINDING,
    bounded_output,
    drive_client,
    sharepoint_available,
)


async def sharepoint_search_files(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")],
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    async def operation(entry):
        async def execute():
            client = await drive_client(ctx, entry)
            return IntegrationAuditOutcome(
                await search_items(client, drive_id=entry.external_id, query=query, limit=limit)
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="sharepoint_search_files",
            operation="search_files",
            execute=execute,
        )

    return bounded_output(
        await run_context_fan_out(ctx, binding=SHAREPOINT_DRIVE_BINDING, operation=operation)
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_search_files",
    function=sharepoint_search_files,
    description=(
        "Searches names, metadata, and content in each selected SharePoint or OneDrive library. "
        "Returns up to 25 file and folder references per library without reading file content."
    ),
    provider="sharepoint",
    label="Search SharePoint Files",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=90,
    output_model=SharePointSearchOutput,
    integration_binding=SHAREPOINT_DRIVE_BINDING,
    availability_check=sharepoint_available,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Searching SharePoint files",
        completed_label="Searched SharePoint files",
        failed_label="Could not search SharePoint files",
        arg_fields=(
            ToolFieldPresentation(key="query", label="Query", format="text"),
            ToolFieldPresentation(
                key="limit", label="Maximum results", format="number", secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
