# apps/api/integrations/google_search_console/tools/query_search_analytics.py

"""Query Search Analytics for selected Search Console sites."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import RunContext

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
from services.integrations.read_audit import read_operation_detail

from ..operations.query_search_analytics import query_search_analytics
from .schemas import (
    GoogleSearchConsoleFilter,
    GoogleSearchConsoleSearchAnalyticsOutput,
)
from .schemas.search_analytics import (
    GoogleSearchConsoleAggregationType,
    GoogleSearchConsoleDataState,
    GoogleSearchConsoleDimension,
    GoogleSearchConsoleSearchType,
)
from .utils.bindings import GOOGLE_SEARCH_CONSOLE_BINDING, RESULTS_FIELD
from .utils.client import google_search_console_client
from .utils.validation import validated_search_analytics_request

_DEFAULT_DIMENSIONS: list[GoogleSearchConsoleDimension] = []


async def google_search_console_query_search_analytics(
    ctx: RunContext[RuntimeDeps],
    start_date: Annotated[str, Field(description="Absolute start date in YYYY-MM-DD format.")],
    end_date: Annotated[str, Field(description="Absolute end date in YYYY-MM-DD format.")],
    dimensions: Annotated[
        list[GoogleSearchConsoleDimension],
        Field(max_length=6, description="Dimensions used to group each result row."),
    ] = _DEFAULT_DIMENSIONS,
    search_type: Annotated[
        GoogleSearchConsoleSearchType,
        Field(description="Search result surface to query."),
    ] = "web",
    filters: Annotated[
        list[GoogleSearchConsoleFilter] | None,
        Field(description="Dimension filters combined with AND."),
    ] = None,
    aggregation_type: Annotated[
        GoogleSearchConsoleAggregationType,
        Field(description="How Search Console aggregates rows."),
    ] = "auto",
    row_limit: Annotated[
        int,
        Field(ge=1, description="Maximum rows returned per selected site."),
    ] = 100,
    start_row: Annotated[
        int,
        Field(ge=0, description="Zero-based provider row offset."),
    ] = 0,
    data_state: Annotated[
        GoogleSearchConsoleDataState,
        Field(description="Final data, or all data including recent partial results."),
    ] = "final",
) -> dict[str, Any]:
    request = validated_search_analytics_request(
        start_date=start_date,
        end_date=end_date,
        dimensions=list(dimensions),
        search_type=search_type,
        filters=filters,
        aggregation_type=aggregation_type,
        row_limit=row_limit,
        start_row=start_row,
        data_state=data_state,
    )

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_search_console_client(ctx, entry)
            result = await query_search_analytics(
                client,
                site_url=entry.external_id,
                request=request,
                max_rows=settings.INTEGRATION_REPORT_MAX_ROWS,
            )
            return IntegrationAuditOutcome(
                result,
                operation_detail=read_operation_detail(
                    entry,
                    operation="query_search_analytics",
                    target_entity_type="google_search_console_site",
                    entity_type="google_search_console_search_analytics",
                    fields={
                        "start_date": request.start_date,
                        "end_date": request.end_date,
                        "dimensions": list(request.dimensions),
                        "search_type": request.search_type,
                        "filter_count": len(request.filters or ()),
                        "row_count": int(result["row_count"]),
                    },
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_search_console_query_search_analytics",
            operation="query_search_analytics",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx,
        binding=GOOGLE_SEARCH_CONSOLE_BINDING,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_search_console_query_search_analytics",
    function=google_search_console_query_search_analytics,
    description=(
        "Query bounded organic-search performance for every Google Search Console site selected "
        "in Active Context. Use absolute YYYY-MM-DD dates covering no more than 16 months. Data "
        "usually lags two to three days, so end three days ago unless the user asks for recent "
        "partial data; use data_state='all' for that request. Row keys are named by dimension. "
        "Page- and query-grouped results are top rows rather than complete totals. Page with "
        "start_row or add filters when truncated is true."
    ),
    provider="google_search_console",
    label="Query Search Analytics",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleSearchConsoleSearchAnalyticsOutput,
    integration_binding=GOOGLE_SEARCH_CONSOLE_BINDING,
    presentation=ToolPresentation(
        icon="google_search_console",
        running_label="Querying Search Analytics",
        completed_label="Queried Search Analytics",
        failed_label="Couldn't Query Search Analytics",
        arg_fields=(
            ToolFieldPresentation(key="start_date", label="Start Date", editable=True),
            ToolFieldPresentation(key="end_date", label="End Date", editable=True),
            ToolFieldPresentation(
                key="dimensions", label="Dimensions", format="list", editable=True
            ),
            ToolFieldPresentation(
                key="filters",
                label="Filters",
                format="records",
                editable=True,
                columns=(
                    ToolFieldColumn(key="dimension", label="Dimension", required=True),
                    ToolFieldColumn(key="operator", label="Operator", required=True),
                    ToolFieldColumn(key="expression", label="Expression", required=True),
                ),
            ),
            ToolFieldPresentation(key="search_type", label="Search Type", editable=True),
            ToolFieldPresentation(
                key="row_limit", label="Row Limit", format="number", editable=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
