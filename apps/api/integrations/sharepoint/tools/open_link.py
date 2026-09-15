# apps/api/integrations/sharepoint/tools/open_link.py

"""Opens a SharePoint link once per selected connection."""

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
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.link_utils import LibraryNotSelectedError, sharepoint_url
from ..operations.resolve_link import resolve_link
from .schemas import SharePointLinkOutput
from .utils import (
    RESULTS_FIELD,
    SHAREPOINT_DRIVE_BINDING,
    bounded_output,
    drive_client,
    link_drive_urls,
    link_request_groups,
    reconcile_link_result,
    sharepoint_available,
)


async def sharepoint_open_link(
    ctx: RunContext[RuntimeDeps],
    url: Annotated[
        str, Field(min_length=1, max_length=8192, description="SharePoint or OneDrive file URL.")
    ],
) -> dict:
    sharepoint_url(url)
    results = []
    for anchor, entries in link_request_groups(ctx, url):
        recovery = {}
        drives = link_drive_urls(entries)

        async def operation(entry, drives=drives, recovery=recovery):
            async def execute():
                client = await drive_client(ctx, entry)
                try:
                    data = await resolve_link(client, url=url, drives=drives)
                except LibraryNotSelectedError as exc:
                    recovery["library"] = exc.library
                    raise
                reference = data["reference"]
                return IntegrationAuditOutcome(
                    data, external_ref=f"{reference.drive_id}:{reference.item_id}"
                )

            return await run_audited_integration_operation(
                ctx, entry, tool_name="sharepoint_open_link", operation="open_link", execute=execute
            )

        resolved = await run_context_scope(
            ctx,
            binding=SHAREPOINT_DRIVE_BINDING,
            provider_scope_id=anchor.external_id,
            operation=operation,
        )
        results.extend(reconcile_link_result(result, entries, recovery) for result in resolved)
    return bounded_output(results)


DEFINITION = RuntimeToolDefinition(
    name="sharepoint_open_link",
    function=sharepoint_open_link,
    description=(
        "Resolves a SharePoint or OneDrive file URL to a reference in a selected library. "
        "Use the returned reference to read the file or list a folder. "
        "If a sharing link is denied, ask for the file's direct URL."
    ),
    provider="sharepoint",
    label="Open SharePoint link",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=90,
    output_model=SharePointLinkOutput,
    integration_binding=SHAREPOINT_DRIVE_BINDING,
    availability_check=sharepoint_available,
    presentation=ToolPresentation(
        icon="sharepoint",
        running_label="Opening SharePoint link",
        completed_label="Opened SharePoint link",
        failed_label="Could not open SharePoint link",
        arg_fields=(ToolFieldPresentation(key="url", label="Link", format="text"),),
        result_fields=RESULTS_FIELD,
    ),
)
