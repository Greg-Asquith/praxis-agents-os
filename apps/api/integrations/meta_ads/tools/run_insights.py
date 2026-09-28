# apps/api/integrations/meta_ads/tools/run_insights.py

"""Runs bounded Insights reports for selected Meta ad accounts."""

import asyncio
import time
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationTimeoutError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.fan_out import run_context_fan_out
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)
from services.integrations.report_results import REPORT_RESULT_GUIDANCE, ReportResultBudget
from utils.metadata import metadata_str

from ..operations.run_insights import run_insights
from ..settings import meta_ads_settings
from ..throttle import ensure_account_available
from .schemas.insights import MetaAdsInsightsFilter, MetaAdsInsightsLevel, MetaAdsInsightsOutput
from .utils.audit import insights_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client
from .utils.form_schema import INSIGHTS_FORM_SCHEMA
from .utils.validation import validated_insights_request

# Reserve result delivery separately from each selected account's terminal audit.
_EXECUTION_SECONDS = 135.0
_AUDIT_SECONDS_PER_ACCOUNT = 3.0


async def meta_ads_run_insights(
    ctx: RunContext[RuntimeDeps],
    fields: Annotated[list[str], Field(min_length=1, max_length=30)],
    since: Annotated[str, Field(description="Start date as YYYY-MM-DD in the account time zone.")],
    until: Annotated[str, Field(description="End date as YYYY-MM-DD in the account time zone.")],
    level: MetaAdsInsightsLevel = "campaign",
    breakdowns: Annotated[list[str] | None, Field(max_length=3)] = None,
    action_breakdowns: Annotated[list[str] | None, Field(max_length=3)] = None,
    attribution_windows: Annotated[list[str] | None, Field(max_length=5)] = None,
    time_increment: str | int = "all_days",
    filters: Annotated[list[MetaAdsInsightsFilter] | None, Field(max_length=10)] = None,
    sort: str | None = None,
    limit: Annotated[int, Field(ge=1)] = 100,
) -> dict[str, Any]:
    started = time.monotonic()
    request = validated_insights_request(
        max_rows=meta_ads_settings.META_ADS_INSIGHTS_MAX_ROWS,
        fields=fields,
        since=since,
        until=until,
        level=level,
        breakdowns=breakdowns or [],
        action_breakdowns=action_breakdowns or [],
        attribution_windows=attribution_windows,
        time_increment=time_increment,
        filters=filters,
        sort=sort,
        limit=limit,
    )
    active_context = ctx.deps.active_context
    account_count = min(
        len(active_context.compatible_entries(META_ADS_BINDING)) if active_context else 0,
        MAX_ACTIVE_CONTEXT_TARGETS,
    )
    deadline = started + _EXECUTION_SECONDS - account_count * _AUDIT_SECONDS_PER_ACCOUNT
    budget = ReportResultBudget("meta_ads", "run_insights")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                async with asyncio.timeout(remaining):
                    ensure_account_available(entry.external_id, operation="run_insights")
                    client = await meta_ads_client(ctx, entry)
                    result = await run_insights(
                        client,
                        account_id=entry.external_id,
                        request=request,
                        max_rows=meta_ads_settings.META_ADS_INSIGHTS_MAX_ROWS,
                        poll_seconds=meta_ads_settings.META_ADS_INSIGHTS_POLL_SECONDS,
                        max_response_bytes=budget.remaining,
                    )
            except TimeoutError:
                raise IntegrationTimeoutError(
                    "The shared Meta Ads report time limit was reached. "
                    "Select fewer accounts or narrow the report and try again.",
                    provider_key="meta_ads",
                    operation="run_insights",
                    error_code="meta_ads_insights_deadline",
                ) from None
            result = result.model_copy(
                update={
                    "currency": metadata_str(entry.permissions_metadata.get("currency")) or "",
                    "timezone_name": metadata_str(entry.permissions_metadata.get("timezone_name"))
                    or "",
                }
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=insights_audit_detail(entry.external_id, request, result),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_run_insights",
            operation="run_insights",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx,
        binding=META_ADS_BINDING,
        operation=operation,
        result_budget=budget,
    )
    if results and all(result.error_code == "meta_ads_invalid_insights" for result in results):
        raise ModelRetry(results[0].error_message or "Correct the Meta Ads Insights request.")
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_run_insights",
    function=meta_ads_run_insights,
    description=(
        "Run a bounded Insights report for every Meta ad account selected in Active Context. "
        "Use absolute since/until dates in the account time zone. Common fields include spend, "
        "impressions, clicks, reach, frequency, cpc, cpm, ctr, actions, action_values, "
        "cost_per_action_type and purchase_roas. Keys hold identity, breakdown, and supported text values; "
        "metrics hold numbers; actions map fields to action_type, value and attribution windows. "
        "Custom conversions also include custom_conversion_id and custom_conversion_name from "
        "one account-scoped lookup. A null name means unresolved metadata, not zero conversions; "
        "use the ID and result notes. Numbers and attribution remain unchanged. Do not sum "
        "overlapping action types into a conversion total. "
        "Object and histogram fields are unsupported; unknown field names are provider-validated. "
        "Money is in major units of data.currency; ctr is percentage points. Recent values can "
        "change for 28 days. Attribution uses each ad set's Ads Manager setting unless explicit "
        "attribution_windows are supplied. Dates must be within 37 months; unique fields within "
        "13 months. With older breakdowns, reach, frequency and cpp are omitted with a note. "
        "Breakdowns: age, gender, country, region, publisher_platform, platform_position, "
        "device_platform, impression_device (not alone). Action breakdowns: action_type, "
        "action_device, action_destination, only with action fields. time_increment is all_days, "
        "monthly, or 1-90. Large queries run as bounded background reports. limit defaults to "
        "100; inspect truncated before treating returned rows as a complete report."
    )
    + REPORT_RESULT_GUIDANCE,
    provider="meta_ads",
    label="Run Meta Ads Insights",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=150,
    output_model=MetaAdsInsightsOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    preview_list_path="results.*.data.rows",
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        form_schema=INSIGHTS_FORM_SCHEMA,
        icon="meta_ads",
        running_label="Running Meta Ads Insights",
        completed_label="Ran Meta Ads Insights",
        failed_label="Couldn't Run Meta Ads Insights",
        arg_fields=(
            ToolFieldPresentation(key="since", label="Start date", editable=True),
            ToolFieldPresentation(key="until", label="End date", editable=True),
            ToolFieldPresentation(
                key="level",
                label="Level",
                editable=True,
                options=tuple(INSIGHTS_FORM_SCHEMA["properties"]["level"]["enum"]),
            ),
            ToolFieldPresentation(key="fields", label="Fields", format="list", editable=True),
            ToolFieldPresentation(
                key="breakdowns", label="Breakdowns", format="list", editable=True, secondary=True
            ),
            ToolFieldPresentation(
                key="action_breakdowns",
                label="Action breakdowns",
                format="list",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="attribution_windows",
                label="Attribution windows",
                format="list",
                editable=True,
                secondary=True,
            ),
            ToolFieldPresentation(
                key="time_increment",
                label="Report interval",
                editable=True,
                secondary=True,
                options=tuple(
                    str(value)
                    for shape in INSIGHTS_FORM_SCHEMA["properties"]["time_increment"]["anyOf"]
                    for value in (
                        shape["enum"]
                        if "enum" in shape
                        else range(shape["minimum"], shape["maximum"] + 1)
                    )
                ),
            ),
            ToolFieldPresentation(
                key="limit", label="Maximum rows", format="number", editable=True, secondary=True
            ),
            ToolFieldPresentation(key="sort", label="Sort", editable=True, secondary=True),
            ToolFieldPresentation(
                key="filters",
                label="Filters",
                format="records",
                editable=True,
                secondary=True,
                columns=(
                    ToolFieldColumn(key="field", label="Field", required=True),
                    ToolFieldColumn(key="operator", label="Operator", required=True),
                    ToolFieldColumn(
                        key="value", label="Value", format="scalar_or_list", required=True
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
