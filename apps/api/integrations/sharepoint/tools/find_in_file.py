# apps/api/integrations/sharepoint/tools/find_in_file.py

"""Find literal text in one referenced SharePoint file."""

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
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.find_in_item import find_in_item
from ..references import SharePointDriveItemReference
from .schemas import SharePointFindOutput
from .utils import (
    RESULTS_FIELD,
    SHAREPOINT_DRIVE_BINDING,
    bounded_output,
    drive_client,
    sharepoint_available,
)


async def sharepoint_find_in_file(
    ctx: RunContext[RuntimeDeps],
    file: Annotated[
        SharePointDriveItemReference,
        Field(description="File reference returned by SharePoint listing or search."),
    ],
    query: Annotated[str, Field(min_length=1, max_length=200)],
    limit: Annotated[int, Field(ge=1, le=25)] = 10,
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await drive_client(ctx, entry)
            return IntegrationAuditOutcome(
                await find_in_item(
                    client,
                    drive_id=entry.external_id,
                    item_id=reference.item_id,
                    query=query,
                    limit=limit,
                ),
                external_ref=reference.item_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="sharepoint_find_in_file",
            operation="find_in_file",
            execute=execute,
        )

    return bounded_output(
        await run_context_targets(
            ctx, binding=SHAREPOINT_DRIVE_BINDING, references=[file], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_find_in_file",
    function=sharepoint_find_in_file,
    description=(
        "Finds case-insensitive literal text throughout a selected SharePoint or OneDrive file. "
        "Downloads and converts the file once, then returns up to 25 bounded excerpts. "
        "Pass an excerpt's byte offset to sharepoint_read_file to read surrounding content. "
        "Search covers the whole converted document; only matching excerpts are returned."
    ),
    provider="sharepoint",
    label="Find in SharePoint file",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=90,
    output_model=SharePointFindOutput,
    integration_binding=SHAREPOINT_DRIVE_BINDING,
    availability_check=sharepoint_available,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Finding text in SharePoint file",
        completed_label="Found text in SharePoint file",
        failed_label="Could not find text in SharePoint file",
        arg_fields=(
            ToolFieldPresentation(
                key="file", label="File", format="entity", entity_kind="sharepoint_drive_item"
            ),
            ToolFieldPresentation(key="query", label="Query", format="text"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
