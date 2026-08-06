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

from ..operations.list_accounts import list_accounts
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    RESULTS_FIELD,
    fan_out_dict,
    google_ads_available,
    run_audited_operation,
)


async def google_ads_list_accounts(ctx: RunContext[RuntimeDeps]) -> dict[str, Any]:
    async def operation(entry: ResolvedContextEntry) -> Any:
        return await run_audited_operation(
            ctx,
            entry,
            tool_name="google_ads_list_accounts",
            operation="list_accounts",
            execute=lambda: list_accounts(
                ctx.deps.db,
                connection_id=entry.connection_id,
                integration_resource_id=entry.integration_resource_id,
            ),
        )

    results = await run_context_fan_out(ctx.deps, binding=GOOGLE_ADS_BINDING, operation=operation)
    return {"results": [fan_out_dict(item) for item in results]}


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
