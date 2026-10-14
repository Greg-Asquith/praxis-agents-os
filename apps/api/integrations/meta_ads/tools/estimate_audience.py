# apps/api/integrations/meta_ads/tools/estimate_audience.py

"""Estimate how many people a Meta targeting draft reaches in each selected ad account."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.estimate_audience import estimate_audience
from ..operations.targeting import MetaAdsTargeting, targeting_problems
from .schemas.targeting import MetaAdsAudienceEstimateOutput
from .utils.audit import audience_estimate_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client

_OPERATION = "estimate_audience"


async def meta_ads_estimate_audience(
    ctx: RunContext[RuntimeDeps],
    targeting: Annotated[MetaAdsTargeting, Field(description="Who the ad set would reach.")],
) -> dict[str, Any]:
    problems = targeting_problems(targeting, special_category=False)
    if problems:
        raise ModelRetry(" ".join(problems))
    audience_accounts = {
        audience.account_id for audience in (*targeting.audiences, *targeting.excluded_audiences)
    }
    if len(audience_accounts) > 1:
        raise ModelRetry("Use audiences from one ad account per estimate.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            client = await meta_ads_client(ctx, entry)
            result = await estimate_audience(
                client, account_id=entry.external_id, targeting=targeting
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=audience_estimate_audit_detail(
                    entry.external_id, targeting, result
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_estimate_audience",
            operation=_OPERATION,
            execute=execute,
        )

    # Audiences belong to one ad account, so a draft using them is estimated only there.
    if audience_accounts:
        results = await run_context_scope(
            ctx,
            binding=META_ADS_BINDING,
            provider_scope_id=audience_accounts.pop(),
            operation=operation,
        )
    else:
        results = await run_context_fan_out(ctx, binding=META_ADS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_estimate_audience",
    function=meta_ads_estimate_audience,
    description=(
        "Estimate how many people a targeting draft reaches, from Meta, for each Meta ad account "
        "selected in Active Context; a draft with audiences is estimated only in their ad "
        "account. Estimate before proposing an ad set and quote the range as Meta's estimate. "
        "Build the draft only from keys meta_ads_search_targeting returned and audience "
        "references from meta_ads_list_assets. locations needs at least one country, region, "
        "city, or postcode; only cities take a radius (10 to 50 miles or 17 to 80 km). "
        "detailed groups are combined with AND and items within a group with OR. "
        "advantage_audience is on by default: Meta may then reach beyond age and gender, "
        "age_min must be 18 to 25, and age_max must be empty. To estimate a fixed age range, "
        "such as 25 to 54, set advantage_audience to false. Null bounds mean Meta has no "
        "estimate; read the notes."
    ),
    provider="meta_ads",
    label="Estimate Meta Ads Audience",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsAudienceEstimateOutput,
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Estimating Meta Ads Audience",
        completed_label="Estimated Meta Ads Audience",
        failed_label="Couldn't Estimate Meta Ads Audience",
        arg_fields=(
            ToolFieldPresentation(key="targeting", label="Targeting", format="structured"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
