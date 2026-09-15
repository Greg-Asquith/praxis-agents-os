# apps/api/integrations/sharepoint/tools/read_file.py

"""Read one referenced file in a selected SharePoint library."""

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

from ..operations.convert_item import convert_item
from ..references import SharePointDriveItemReference
from .schemas import SharePointFileOutput
from .utils import (
    RESULTS_FIELD,
    SHAREPOINT_DRIVE_BINDING,
    bounded_output,
    drive_client,
    sharepoint_available,
)


async def sharepoint_read_file(
    ctx: RunContext[RuntimeDeps],
    file: Annotated[
        SharePointDriveItemReference,
        Field(description="File reference returned by SharePoint listing or search."),
    ],
) -> dict:
    async def operation(entry, references):
        reference = references[0]

        async def execute():
            client = await drive_client(ctx, entry)
            return IntegrationAuditOutcome(
                await convert_item(client, drive_id=entry.external_id, item_id=reference.item_id),
                external_ref=reference.item_id,
            )

        return await run_audited_integration_operation(
            ctx, entry, tool_name="sharepoint_read_file", operation="read_file", execute=execute
        )

    return bounded_output(
        await run_context_targets(
            ctx, binding=SHAREPOINT_DRIVE_BINDING, references=[file], operation=operation
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_read_file",
    function=sharepoint_read_file,
    description=(
        "Reads a document or text file in a selected SharePoint or OneDrive library using "
        "its file reference. Returns up to 64 KiB of Markdown with a citation link. "
        "Images, folders, packages, and files above the download limit are unsupported."
    ),
    provider="sharepoint",
    label="Read SharePoint file",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=90,
    output_model=SharePointFileOutput,
    integration_binding=SHAREPOINT_DRIVE_BINDING,
    availability_check=sharepoint_available,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Reading SharePoint file",
        completed_label="Read SharePoint file",
        failed_label="Could not read SharePoint file",
        arg_fields=(
            ToolFieldPresentation(
                key="file", label="File", format="entity", entity_kind="sharepoint_drive_item"
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
