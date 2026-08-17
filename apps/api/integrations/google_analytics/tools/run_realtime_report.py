# apps/api/integrations/google_analytics/tools/run_realtime_report.py

"""Run Google Analytics realtime report runtime tool."""

from typing import Annotated, Any

from pydantic import Field, ValidationError
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

from ..operations.run_realtime_report import run_realtime_report
from .schemas import (
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsMetricAggregation,
    GoogleAnalyticsMinuteRange,
    GoogleAnalyticsOrderBy,
    GoogleAnalyticsRunRealtimeReportInput,
    GoogleAnalyticsRunRealtimeReportOutput,
)
from .utils import (
    GOOGLE_ANALYTICS_BINDING,
    RESULTS_FIELD,
    google_analytics_available,
    google_analytics_client,
)
from .utils.audit import read_operation_detail
from .utils.validation import (
    validate_field_selection,
    validate_filter_kinds,
    validate_order_bys,
)

_DEFAULT_MINUTE_RANGE = GoogleAnalyticsMinuteRange(
    start_minutes_ago=29,
    end_minutes_ago=0,
)


async def google_analytics_run_realtime_report(
    ctx: RunContext[RuntimeDeps],
    metrics: Annotated[
        list[str],
        Field(min_length=1, max_length=10, description="One to ten realtime metric API names."),
    ],
    dimensions: Annotated[
        list[str],
        Field(max_length=9, description="Zero to nine realtime dimension API names."),
    ],
    minute_ranges: Annotated[
        list[GoogleAnalyticsMinuteRange] | None,
        Field(description="One or two minute ranges; defaults to the last 30 minutes."),
    ] = None,
    dimension_filter: Annotated[
        list[GoogleAnalyticsFieldFilter] | None,
        Field(description="Dimension filters combined with AND."),
    ] = None,
    metric_filter: Annotated[
        list[GoogleAnalyticsFieldFilter] | None,
        Field(description="Metric filters combined with AND."),
    ] = None,
    order_bys: Annotated[
        list[GoogleAnalyticsOrderBy] | None,
        Field(description="Metric or dimension ordering rules."),
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, description="Maximum rows returned per selected property."),
    ] = 100,
    metric_aggregations: Annotated[
        list[GoogleAnalyticsMetricAggregation] | None,
        Field(description="Optional TOTAL, MINIMUM, or MAXIMUM metric rows."),
    ] = None,
) -> dict[str, Any]:
    request = _validated_request(
        metrics=metrics,
        dimensions=dimensions,
        minute_ranges=minute_ranges,
        dimension_filter=dimension_filter,
        metric_filter=metric_filter,
        order_bys=order_bys,
        limit=limit,
        metric_aggregations=metric_aggregations,
    )

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_analytics_client(ctx, entry)
            result = await run_realtime_report(
                client,
                property_id=entry.external_id,
                request=request,
                max_rows=settings.INTEGRATION_REPORT_MAX_ROWS,
            )
            return IntegrationAuditOutcome(
                result,
                operation_detail=read_operation_detail(
                    entry,
                    operation="run_realtime_report",
                    fields={
                        "metric_count": len(request.metrics),
                        "dimension_count": len(request.dimensions),
                        "window": [
                            {
                                "start_minutes_ago": item.start_minutes_ago,
                                "end_minutes_ago": item.end_minutes_ago,
                            }
                            for item in request.minute_ranges or []
                        ],
                    },
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_analytics_run_realtime_report",
            operation="run_realtime_report",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ANALYTICS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


def _validated_request(**values: Any) -> GoogleAnalyticsRunRealtimeReportInput:
    metrics = values["metrics"]
    dimensions = values["dimensions"]
    minute_ranges = values["minute_ranges"]
    validate_field_selection(metrics, dimensions)
    if minute_ranges is not None and not 1 <= len(minute_ranges) <= 2:
        raise ModelRetry("Provide one or two Google Analytics realtime minute ranges.")
    if values["limit"] > settings.INTEGRATION_REPORT_MAX_ROWS:
        raise ModelRetry(f"Set limit to {settings.INTEGRATION_REPORT_MAX_ROWS} rows or fewer.")
    for item in minute_ranges or []:
        if not 0 <= item.start_minutes_ago <= 29 or not 0 <= item.end_minutes_ago <= 29:
            raise ModelRetry("Set realtime minute bounds between 0 and 29 minutes ago.")
        if item.start_minutes_ago < item.end_minutes_ago:
            raise ModelRetry("Set start_minutes_ago greater than or equal to end_minutes_ago.")
        if item.name is not None and item.name.startswith(("date_range_", "RESERVED_")):
            raise ModelRetry(
                "Choose a minute range name that does not begin with date_range_ or RESERVED_."
            )
    validate_filter_kinds(values["dimension_filter"], metric=False)
    validate_filter_kinds(values["metric_filter"], metric=True)
    validate_order_bys(values["order_bys"], metrics=metrics, dimensions=dimensions)
    values["minute_ranges"] = minute_ranges or [_DEFAULT_MINUTE_RANGE]
    try:
        return GoogleAnalyticsRunRealtimeReportInput.model_validate(values)
    except ValidationError as exc:
        message = exc.errors(include_url=False)[0]["msg"]
        raise ModelRetry(
            f"Correct the Google Analytics realtime report request: {message}."
        ) from exc


DEFINITION = RuntimeToolDefinition(
    name="google_analytics_run_realtime_report",
    function=google_analytics_run_realtime_report,
    description=(
        "Run a bounded read-only report over the last 30 minutes for every Google Analytics "
        "property selected in Active Context. Prefer realtime metrics activeUsers, "
        "screenPageViews, eventCount, and keyEvents with dimensions unifiedScreenName, country, "
        "city, deviceCategory, eventName, minutesAgo, and platform. Standard-report dimensions "
        "such as date and sessionSource are not valid here. Results are per selected property."
    ),
    provider="google_analytics",
    label="Run Google Analytics Realtime Report",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=30,
    output_model=GoogleAnalyticsRunRealtimeReportOutput,
    integration_binding=GOOGLE_ANALYTICS_BINDING,
    availability_check=google_analytics_available,
    presentation=ToolPresentation(
        icon="google_analytics",
        running_label="Running Google Analytics Realtime Report",
        completed_label="Ran Google Analytics Realtime Report",
        failed_label="Couldn't Run Google Analytics Realtime Report",
        arg_fields=(
            ToolFieldPresentation(key="metrics", label="Metrics", format="list", editable=True),
            ToolFieldPresentation(
                key="dimensions",
                label="Dimensions",
                format="list",
                editable=True,
            ),
            ToolFieldPresentation(
                key="limit",
                label="Row Limit",
                format="number",
                editable=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
