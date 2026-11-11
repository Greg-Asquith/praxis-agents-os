# apps/api/integrations/google_ads/tools/get_accounts.py

"""Return settings and current cost for every selected Google Ads account."""

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
from .schemas.accounts import GoogleAdsAccountsOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)


async def google_ads_get_accounts(ctx: RunContext[RuntimeDeps]) -> dict[str, Any]:
    budget = ReportResultBudget("google_ads", "get_account")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            client = await google_ads_client(ctx, entry)
            account = await get_account(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                max_response_bytes=budget.remaining,
            )
            return IntegrationAuditOutcome(account)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_get_accounts",
            operation="get_account",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx, binding=GOOGLE_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_get_accounts",
    function=google_ads_get_accounts,
    description=(
        "Read name, status, currency, time zone, manager flag, auto-tagging, today's and "
        "this month's cost, and billing for every Google Ads account selected in Active "
        "Context. Money is exact decimal strings in major units of data.currency, and dates "
        "follow data.time_zone. data.billing names who pays, the account spending limit in "
        "force with the amount left, queued limits, and changes waiting for Google's review. "
        "billing.state is running_low when less than seven days of this month's average daily "
        "cost is left, and limit_reached when ads have stopped for the limit. "
        "monthly_invoicing false means billing is managed in Google Ads, not an error. "
        "Manager accounts have null costs and billing; read their client accounts instead."
    ),
    provider="google_ads",
    label="Get Google Ads Accounts",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=GoogleAdsAccountsOutput,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Reading Google Ads Accounts",
        completed_label="Read Google Ads Accounts",
        failed_label="Couldn't Read Google Ads Accounts",
        result_fields=RESULTS_FIELD,
    ),
)
