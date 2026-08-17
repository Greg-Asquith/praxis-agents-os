# apps/api/integrations/google_analytics/tools/list_report_fields.py

"""List Google Analytics report fields runtime tool."""

from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

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

from ..operations.list_report_fields import list_report_fields
from .schemas import GoogleAnalyticsListReportFieldsOutput
from .utils import (
    GOOGLE_ANALYTICS_BINDING,
    RESULTS_FIELD,
    google_analytics_available,
    google_analytics_client,
)


async def google_analytics_list_report_fields(
    ctx: RunContext[RuntimeDeps],
    search: Annotated[
        str | None,
        Field(description="Optional API-name or display-name search text."),
    ] = None,
    kind: Annotated[
        Literal["dimensions", "metrics", "both"],
        Field(description="Return dimensions, metrics, or both kinds."),
    ] = "both",
    custom_only: Annotated[
        bool,
        Field(description="Return only custom dimensions or metrics."),
    ] = False,
    limit: Annotated[
        int,
        Field(ge=1, le=200, description="Maximum fields returned per kind and property."),
    ] = 50,
) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise ModelRetry("Set limit between 1 and 200 report fields per kind.")
    normalized_search = (search or "").strip() or None

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_analytics_client(ctx, entry)
            result = await list_report_fields(
                client,
                property_id=entry.external_id,
                search=normalized_search,
                kind=kind,
                custom_only=custom_only,
                limit=limit,
            )
            return IntegrationAuditOutcome(result)

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_analytics_list_report_fields",
            operation="list_report_fields",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ANALYTICS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="google_analytics_list_report_fields",
    function=google_analytics_list_report_fields,
    description=(
        "List exact standard and custom dimension and metric API names for every Google Analytics "
        "property selected in Active Context. Results are per selected property and can be "
        "searched or limited to custom fields. Use the returned api_name values in "
        "google_analytics_run_report, and check metric blocked_reasons before interpreting "
        "zero values."
    ),
    provider="google_analytics",
    label="List Google Analytics Report Fields",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAnalyticsListReportFieldsOutput,
    integration_binding=GOOGLE_ANALYTICS_BINDING,
    availability_check=google_analytics_available,
    presentation=ToolPresentation(
        icon="google_analytics",
        running_label="Listing Google Analytics Report Fields",
        completed_label="Listed Google Analytics Report Fields",
        failed_label="Couldn't List Google Analytics Report Fields",
        arg_fields=(
            ToolFieldPresentation(key="search", label="Search", editable=True),
            ToolFieldPresentation(
                key="kind",
                label="Field Type",
                editable=True,
                options=("dimensions", "metrics", "both"),
            ),
            ToolFieldPresentation(
                key="custom_only",
                label="Custom Fields Only",
                format="boolean",
            ),
            ToolFieldPresentation(
                key="limit",
                label="Limit Per Type",
                format="number",
                editable=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
