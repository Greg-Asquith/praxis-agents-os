# apps/api/integrations/google_ads/tools/run_report.py

"""Run Google Ads GAQL report runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out

from ..operations.run_report import run_report
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    RESULTS_FIELD,
    fan_out_dict,
    google_ads_available,
    google_ads_client,
    login_customer_id,
    run_audited_operation,
)


async def google_ads_run_report(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(description="Google Ads Query Language SELECT query.")],
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query.upper().startswith("SELECT"):
        raise ModelRetry("google_ads_run_report requires a GAQL SELECT query.")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            return await run_report(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                query=normalized_query,
                max_rows=settings.INTEGRATION_REPORT_MAX_ROWS,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="google_ads_run_report",
            operation="run_report",
            execute=execute,
        )

    results = await run_context_fan_out(ctx.deps, binding=GOOGLE_ADS_BINDING, operation=operation)
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_run_report",
    function=google_ads_run_report,
    description="Run a bounded read-only GAQL report for selected Google Ads accounts.",
    provider="google_ads",
    label="Run Google Ads Report",
    effect=TOOL_EFFECT_READ,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsOutput,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Running Google Ads Report",
        completed_label="Ran Google Ads Report",
        failed_label="Couldn't Run Google Ads Report",
        arg_fields=(ToolFieldPresentation(key="query", label="GAQL Query", format="multiline"),),
        result_fields=RESULTS_FIELD,
    ),
)
