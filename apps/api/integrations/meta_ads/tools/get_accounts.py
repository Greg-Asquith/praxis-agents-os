# apps/api/integrations/meta_ads/tools/get_accounts.py

"""Return current account status and spending for selected Meta accounts."""

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
from services.integrations.report_results import ReportResultBudget

from ..operations.get_account import get_account
from ..throttle import ensure_account_available
from .schemas.accounts import MetaAdsAccountsOutput
from .utils.audit import accounts_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client


async def meta_ads_get_accounts(ctx: RunContext[RuntimeDeps]) -> dict[str, Any]:
    budget = ReportResultBudget("meta_ads", "get_account")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            ensure_account_available(entry.external_id, operation="get_account")
            client = await meta_ads_client(ctx, entry)
            result = await get_account(
                client, account_id=entry.external_id, max_response_bytes=budget.remaining
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=accounts_audit_detail(entry.external_id),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_get_accounts",
            operation="get_account",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx, binding=META_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_get_accounts",
    function=meta_ads_get_accounts,
    description=(
        "Read current status, disable reason, currency, time zone and spending for every Meta "
        "ad account selected in Active Context. Money uses exact decimal strings in major "
        "units of data.currency. A null spend_cap means no account spending cap is set. "
        "spend_cap_remaining is the cap minus amount_spent when both are available."
    ),
    provider="meta_ads",
    label="Get Meta Ads accounts",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsAccountsOutput,
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Reading Meta Ads accounts",
        completed_label="Read Meta Ads accounts",
        failed_label="Couldn't read Meta Ads accounts",
        result_fields=RESULTS_FIELD,
    ),
)
