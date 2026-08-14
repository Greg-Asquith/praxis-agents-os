# apps/api/integrations/google_ads/tools/run_report.py

"""Run Google Ads GAQL report runtime tool."""

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
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.run_report import run_report
from .schemas import GoogleAdsRunReportOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)


async def google_ads_run_report(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[
        str,
        Field(
            description=(
                "Google Ads Query Language SELECT query. Selected fields determine each row's "
                "nested lowerCamelCase shape: SELECT campaign.id, metrics.clicks returns "
                "row['campaign']['id'] and row['metrics']['clicks']."
            )
        ),
    ],
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query.upper().startswith("SELECT"):
        raise ModelRetry("google_ads_run_report requires a GAQL SELECT query.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            result = await run_report(
                client,
                customer_id=entry.external_id,
                currency_code=str(entry.permissions_metadata.get("currency_code", "")),
                login_customer_id=login_customer_id(entry),
                query=normalized_query,
                max_rows=settings.INTEGRATION_REPORT_MAX_ROWS,
            )
            return IntegrationAuditOutcome(result)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_run_report",
            operation="run_report",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ADS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_run_report",
    function=google_ads_run_report,
    description=(
        "Run a bounded read-only GAQL report for the Google Ads accounts selected in Active "
        "Context. The result has `results`, one fan-out entry per selected account; inspect each "
        "entry's `status` and `error_message`, then read successful rows from `data.rows`. "
        "`data` also contains `currency_code`, `row_count`, `truncated`, and `truncation_note`. "
        "Each row mirrors the GAQL SELECT paths as nested lowerCamelCase objects: selecting "
        "`campaign.id` and `metrics.clicks` yields `row['campaign']['id']` and "
        "`row['metrics']['clicks']`. Google Ads int64 values may be serialized as strings."
    ),
    provider="google_ads",
    label="Run Google Ads Report",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsRunReportOutput,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Running Google Ads Report",
        completed_label="Ran Google Ads Report",
        failed_label="Couldn't Run Google Ads Report",
        arg_fields=(
            ToolFieldPresentation(
                key="query",
                label="GAQL Query",
                format="multiline",
                editable=True,
                placeholder="SELECT campaign.id, metrics.clicks FROM campaign",
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
