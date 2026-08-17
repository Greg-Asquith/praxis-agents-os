# apps/api/integrations/google_analytics/tools/list_google_ads_links.py

"""List Google Ads links for selected Google Analytics properties."""

from typing import Any

from pydantic_ai import RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_google_ads_links import list_google_ads_links
from .schemas import GoogleAnalyticsListGoogleAdsLinksOutput
from .utils import (
    GOOGLE_ANALYTICS_BINDING,
    RESULTS_FIELD,
    google_analytics_available,
    google_analytics_client,
)
from .utils.audit import read_operation_detail


async def google_analytics_list_google_ads_links(
    ctx: RunContext[RuntimeDeps],
) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_analytics_client(ctx, entry)
            result = await list_google_ads_links(client, property_id=entry.external_id)
            return IntegrationAuditOutcome(
                result,
                operation_detail=read_operation_detail(
                    entry,
                    operation="list_google_ads_links",
                    entity_type="google_analytics_google_ads_link",
                    fields={"link_count": int(result["link_count"])},
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_analytics_list_google_ads_links",
            operation="list_google_ads_links",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx,
        binding=GOOGLE_ANALYTICS_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_analytics_list_google_ads_links",
    function=google_analytics_list_google_ads_links,
    description=(
        "List the Google Ads accounts linked to every Google Analytics property selected in "
        "Active Context. Customer ids contain digits matching Google Ads account ids; format "
        "them as 123-456-7890 for people. The same ids appear in Analytics reports as "
        "sessionGoogleAdsCustomerId. Confirm the link before comparing Ads and Analytics data."
    ),
    provider="google_analytics",
    label="List Linked Google Ads Accounts",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=30,
    output_model=GoogleAnalyticsListGoogleAdsLinksOutput,
    integration_binding=GOOGLE_ANALYTICS_BINDING,
    availability_check=google_analytics_available,
    presentation=ToolPresentation(
        icon="google_analytics",
        running_label="Listing Linked Google Ads Accounts",
        completed_label="Listed Linked Google Ads Accounts",
        failed_label="Couldn't List Linked Google Ads Accounts",
        result_fields=RESULTS_FIELD,
    ),
)
