# apps/api/integrations/meta_ads/tools/list_conversions.py

"""Discover custom conversions and custom events in selected Meta ad accounts."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

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
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.report_results import REPORT_RESULT_GUIDANCE, ReportResultBudget

from ..operations.list_conversions import list_conversions
from ..throttle import ensure_account_available
from .schemas.conversions import CUSTOM_CONVERSIONS_MAX_ROWS, MetaAdsConversionsOutput
from .utils.audit import conversions_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client


async def meta_ads_list_conversions(
    ctx: RunContext[RuntimeDeps],
    limit: Annotated[int, Field(ge=1, le=CUSTOM_CONVERSIONS_MAX_ROWS)] = 100,
) -> dict[str, Any]:
    budget = ReportResultBudget("meta_ads", "list_conversions")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            ensure_account_available(entry.external_id, operation="list_conversions")
            client = await meta_ads_client(ctx, entry)
            result = await list_conversions(
                client,
                account_id=entry.external_id,
                limit=limit,
                budget=ReportResultBudget("meta_ads", "list_conversions", maximum=budget.remaining),
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=conversions_audit_detail(entry.external_id, result),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_list_conversions",
            operation="list_conversions",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx, binding=META_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_list_conversions",
    function=meta_ads_list_conversions,
    description=(
        "List custom conversions and custom events for every Meta ad account selected in "
        "Active Context. Each item has kind, its Insights action_type, and recent_conversions "
        "between recent_since and recent_until (last 90 days, each ad set's attribution). "
        "Custom conversions come from the account's definitions with IDs, descriptions, and "
        "archived or unavailable flags; use IDs to distinguish duplicate names. Custom events "
        "are pixel events Meta attributed to ads in that window; events without recent ad "
        "conversions are not listed. Null recent_conversions means none were reported. "
        "limit caps custom conversions at 100 by default with a maximum of 500; inspect "
        "truncated and notes."
    )
    + REPORT_RESULT_GUIDANCE,
    provider="meta_ads",
    label="List Meta Ads Conversion Actions",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsConversionsOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    preview_list_path="results.*.data.conversions",
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Listing Meta Ads conversion actions",
        completed_label="Listed Meta Ads conversion actions",
        failed_label="Couldn't list Meta Ads conversion actions",
        arg_fields=(
            ToolFieldPresentation(
                key="limit", label="Maximum custom conversions", format="number", editable=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
