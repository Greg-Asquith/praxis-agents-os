# apps/api/integrations/meta_ads/tools/search_targeting.py

"""Find Meta targeting options by name: places, interests, behaviours, demographics, and languages."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.report_results import ReportResultBudget

from ..operations.search_targeting import search_targeting
from .schemas.targeting import (
    MAX_TARGETING_RESULTS,
    MetaAdsTargetingKind,
    MetaAdsTargetingSearchOutput,
)
from .utils.audit import targeting_search_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client

_OPERATION = "search_targeting"


async def meta_ads_search_targeting(
    ctx: RunContext[RuntimeDeps],
    kind: MetaAdsTargetingKind,
    query: Annotated[str, Field(min_length=1, max_length=100)],
    country_code: Annotated[
        str | None,
        Field(pattern=r"^[A-Z]{2}$", description="Limits places to one country, such as GB."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_TARGETING_RESULTS)] = 20,
) -> dict[str, Any]:
    active_context = ctx.deps.active_context
    entries = active_context.compatible_entries(META_ADS_BINDING) if active_context else ()
    if not entries:
        raise ModelRetry(
            "No compatible resources in the active context. "
            "Ask the user to select a context that includes Meta Ads."
        )
    budget = ReportResultBudget("meta_ads", _OPERATION)

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            client = await meta_ads_client(ctx, entry)
            result = await search_targeting(
                client,
                account_id=entry.external_id,
                kind=kind,
                query=query,
                country_code=country_code,
                limit=limit,
                max_response_bytes=budget.remaining,
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=targeting_search_audit_detail(entry.external_id, kind, result),
            )

        return await run_audited_integration_operation(
            ctx, entry, tool_name="meta_ads_search_targeting", operation=_OPERATION, execute=execute
        )

    # Meta's targeting keys are the same for every ad account, so one account searches.
    results = await run_context_scope(
        ctx, binding=META_ADS_BINDING, provider_scope_id=entries[0].external_id, operation=operation
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_search_targeting",
    function=meta_ads_search_targeting,
    description=(
        "Find Meta targeting options by name and get the keys a targeting draft needs. kind is "
        "country, region, city, postcode, interest, behavior, demographic, or language. Use "
        "country_code to limit places to one country. Each option has its key, a name for "
        "display, and, for interests, behaviours, and demographics, Meta's approximate audience "
        "size. Pass key and kind unchanged into meta_ads_estimate_audience locations, detailed "
        "items, or languages; give demographics their category too. Never invent keys or "
        "target by free text. Meta's keys don't depend on the ad account, so one selected "
        "account runs the search."
    ),
    provider="meta_ads",
    label="Search Meta Ads Targeting",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsTargetingSearchOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Searching Meta Ads Targeting",
        completed_label="Searched Meta Ads Targeting",
        failed_label="Couldn't Search Meta Ads Targeting",
        arg_fields=(
            ToolFieldPresentation(key="kind", label="Kind"),
            ToolFieldPresentation(key="query", label="Search"),
            ToolFieldPresentation(key="country_code", label="Country"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
