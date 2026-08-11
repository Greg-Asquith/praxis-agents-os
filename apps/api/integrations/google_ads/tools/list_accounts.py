# apps/api/integrations/google_ads/tools/list_accounts.py

"""List persisted Google Ads account hierarchy runtime tool."""

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

from ..operations.list_accounts import list_accounts
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    RESULTS_FIELD,
    google_ads_available,
)


async def google_ads_list_accounts(ctx: RunContext[RuntimeDeps]) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome[Any]:
            result = await list_accounts(
                ctx.deps.db,
                connection_id=entry.connection_id,
                integration_resource_id=entry.integration_resource_id,
            )
            return IntegrationAuditOutcome(result)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_list_accounts",
            operation="list_accounts",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ADS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_list_accounts",
    function=google_ads_list_accounts,
    description="List the persisted Google Ads account hierarchy for the active context.",
    provider="google_ads",
    label="List Google Ads Accounts",
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsOutput,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Listing Google Ads Accounts",
        completed_label="Listed Google Ads Accounts",
        failed_label="Couldn't List Google Ads Accounts",
        result_fields=RESULTS_FIELD,
    ),
)
