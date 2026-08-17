# apps/api/integrations/google_analytics/tools/run_report.py

"""Run Google Analytics report runtime tool."""

import re
from datetime import date
from typing import Annotated, Any

from pydantic import Field, ValidationError
from pydantic_ai import ModelRetry, RunContext

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
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.run_report import run_report
from .schemas import (
    GoogleAnalyticsDateRange,
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsMetricAggregation,
    GoogleAnalyticsOrderBy,
    GoogleAnalyticsRunReportInput,
    GoogleAnalyticsRunReportOutput,
)
from .utils import (
    GOOGLE_ANALYTICS_BINDING,
    RESULTS_FIELD,
    google_analytics_available,
    google_analytics_client,
)
from .utils.validation import (
    validate_field_selection,
    validate_filter_kinds,
    validate_order_bys,
)

_RELATIVE_DATE_PATTERN = re.compile(r"^(?:today|yesterday|[0-9]+daysAgo)$")
_ABSOLUTE_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_RESERVED_DATE_RANGE_PREFIXES = ("date_range_", "RESERVED_")


async def google_analytics_run_report(
    ctx: RunContext[RuntimeDeps],
    metrics: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=10,
            description="One to ten exact metric API names.",
        ),
    ],
    dimensions: Annotated[
        list[str],
        Field(max_length=9, description="Zero to nine exact dimension API names."),
    ],
    date_ranges: Annotated[
        list[GoogleAnalyticsDateRange],
        Field(min_length=1, max_length=4, description="One to four report date ranges."),
    ],
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
    offset: Annotated[int, Field(ge=0, description="Zero-based provider row offset.")] = 0,
    metric_aggregations: Annotated[
        list[GoogleAnalyticsMetricAggregation] | None,
        Field(description="Optional TOTAL, MINIMUM, or MAXIMUM metric rows."),
    ] = None,
    keep_empty_rows: Annotated[
        bool,
        Field(description="Include rows whose metric values are all zero."),
    ] = False,
) -> dict[str, Any]:
    request = _validated_request(
        metrics=metrics,
        dimensions=dimensions,
        date_ranges=date_ranges,
        dimension_filter=dimension_filter,
        metric_filter=metric_filter,
        order_bys=order_bys,
        limit=limit,
        offset=offset,
        metric_aggregations=metric_aggregations,
        keep_empty_rows=keep_empty_rows,
    )

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_analytics_client(ctx, entry)
            result = await run_report(
                client,
                property_id=entry.external_id,
                request=request,
                max_rows=settings.INTEGRATION_REPORT_MAX_ROWS,
            )
            return IntegrationAuditOutcome(result)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_analytics_run_report",
            operation="run_report",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ANALYTICS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


def _validated_request(**values: Any) -> GoogleAnalyticsRunReportInput:
    metrics = values["metrics"]
    dimensions = values["dimensions"]
    date_ranges = values["date_ranges"]
    validate_field_selection(metrics, dimensions)
    if not 1 <= len(date_ranges) <= 4:
        raise ModelRetry("Provide between 1 and 4 Google Analytics date ranges.")
    if values["limit"] > settings.INTEGRATION_REPORT_MAX_ROWS:
        raise ModelRetry(f"Set limit to {settings.INTEGRATION_REPORT_MAX_ROWS} rows or fewer.")
    for item in date_ranges:
        for label, value in (("start_date", item.start_date), ("end_date", item.end_date)):
            if not _valid_date_token(value):
                raise ModelRetry(
                    f"Set {label} to YYYY-MM-DD, today, yesterday, or NdaysAgo; got {value!r}."
                )
        if item.name is not None and item.name.startswith(_RESERVED_DATE_RANGE_PREFIXES):
            raise ModelRetry(
                "Choose a date range name that does not begin with date_range_ or RESERVED_."
            )
        absolute_start = _absolute_date(item.start_date)
        absolute_end = _absolute_date(item.end_date)
        if (
            absolute_start is not None
            and absolute_end is not None
            and absolute_start > absolute_end
        ):
            raise ModelRetry("Set each absolute start_date on or before its end_date.")
    validate_filter_kinds(values["dimension_filter"], metric=False)
    validate_filter_kinds(values["metric_filter"], metric=True)
    validate_order_bys(values["order_bys"], metrics=metrics, dimensions=dimensions)
    try:
        return GoogleAnalyticsRunReportInput.model_validate(values)
    except ValidationError as exc:
        message = exc.errors(include_url=False)[0]["msg"]
        raise ModelRetry(f"Correct the Google Analytics report request: {message}.") from exc


def _valid_date_token(value: str) -> bool:
    if _RELATIVE_DATE_PATTERN.fullmatch(value):
        return True
    return _absolute_date(value) is not None


def _absolute_date(value: str) -> date | None:
    if not _ABSOLUTE_DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


DEFINITION = RuntimeToolDefinition(
    name="google_analytics_run_report",
    function=google_analytics_run_report,
    description=(
        "Run a bounded read-only report for every Google Analytics property selected in Active "
        "Context. Results are per selected property. Use google_analytics_list_report_fields for "
        "exact standard and custom API names. Dates accept YYYY-MM-DD, NdaysAgo, today, and "
        "yesterday; date-based reports commonly lag 24-48 hours, so prefer yesterday as the end "
        "date. Each successful result exposes typed rows, total row_count, truncated and "
        "truncation_note fields, and metadata.sampled with sampling notes."
        " Check metadata.active_metric_restrictions before interpreting zero metric values."
    ),
    provider="google_analytics",
    label="Run Google Analytics Report",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAnalyticsRunReportOutput,
    integration_binding=GOOGLE_ANALYTICS_BINDING,
    availability_check=google_analytics_available,
    presentation=ToolPresentation(
        icon="google_analytics",
        running_label="Running Google Analytics Report",
        completed_label="Ran Google Analytics Report",
        failed_label="Couldn't Run Google Analytics Report",
        arg_fields=(
            ToolFieldPresentation(key="metrics", label="Metrics", format="list", editable=True),
            ToolFieldPresentation(
                key="dimensions",
                label="Dimensions",
                format="list",
                editable=True,
            ),
            ToolFieldPresentation(
                key="date_ranges",
                label="Date Ranges",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(key="start_date", label="Start Date", required=True),
                    ToolFieldColumn(key="end_date", label="End Date", required=True),
                    ToolFieldColumn(key="name", label="Name"),
                ),
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
