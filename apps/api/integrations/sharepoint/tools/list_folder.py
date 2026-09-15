# apps/api/integrations/sharepoint/tools/list_folder.py

"""List roots or one referenced folder in the selected SharePoint libraries."""

from typing import Annotated

from pydantic import Field
from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolPresentation,
)
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_children import list_children
from ..references import SharePointDriveItemReference
from .schemas import FolderOutput
from .utils import (
    RESULTS_FIELD,
    SHAREPOINT_DRIVE_BINDING,
    bounded_output,
    drive_client,
    sharepoint_available,
)


async def sharepoint_list_folder(
    ctx: RunContext[RuntimeDeps],
    folder: Annotated[
        SharePointDriveItemReference | None,
        Field(description="Folder reference from a previous listing; omit to list library roots."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict:
    async def operation(entry, references=()):
        folder_id = references[0].item_id if references else None

        async def execute():
            client = await drive_client(ctx, entry)
            return IntegrationAuditOutcome(
                await list_children(
                    client, drive_id=entry.external_id, folder_id=folder_id, limit=limit
                ),
                external_ref=folder_id,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="sharepoint_list_folder",
            operation="list_folder",
            execute=execute,
        )

    if folder is not None:
        results = await run_context_targets(
            ctx, binding=SHAREPOINT_DRIVE_BINDING, references=[folder], operation=operation
        )
    else:
        results = await run_context_fan_out(
            ctx, binding=SHAREPOINT_DRIVE_BINDING, operation=operation
        )
    return bounded_output(results)


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_list_folder",
    function=sharepoint_list_folder,
    description=(
        "Lists up to 200 files and folders per selected SharePoint or OneDrive library. "
        "Omit folder to list library roots, or supply a folder reference from a previous listing. "
        "Reports whether more items exist; does not read file content."
    ),
    provider="sharepoint",
    label="List SharePoint folder",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=90,
    output_model=FolderOutput,
    integration_binding=SHAREPOINT_DRIVE_BINDING,
    availability_check=sharepoint_available,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Listing SharePoint folder",
        completed_label="Listed SharePoint folder",
        failed_label="Could not list SharePoint folder",
        result_fields=RESULTS_FIELD,
    ),
)
