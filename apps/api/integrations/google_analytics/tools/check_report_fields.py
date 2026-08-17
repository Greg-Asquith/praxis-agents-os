# apps/api/integrations/google_analytics/tools/check_report_fields.py

"""Check Google Analytics report-field compatibility runtime tool."""

from typing import Annotated, Any

from pydantic import Field, ValidationError
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

from ..operations.check_report_fields import check_report_fields
from .schemas import (
    GoogleAnalyticsCheckReportFieldsInput,
    GoogleAnalyticsCheckReportFieldsOutput,
    GoogleAnalyticsFieldFilter,
)
from .utils import (
    GOOGLE_ANALYTICS_BINDING,
    RESULTS_FIELD,
    google_analytics_available,
    google_analytics_client,
)
from .utils.audit import read_operation_detail
from .utils.validation import validate_field_selection, validate_filter_kinds


async def google_analytics_check_report_fields(
    ctx: RunContext[RuntimeDeps],
    metrics: Annotated[
        list[str],
        Field(max_length=10, description="Metric API names in the compatible base report."),
    ],
    dimensions: Annotated[
        list[str],
        Field(max_length=9, description="Dimension API names in the compatible base report."),
    ],
    candidate_metrics: Annotated[
        list[str],
        Field(max_length=10, description="Metric API names to check for addition."),
    ],
    candidate_dimensions: Annotated[
        list[str],
        Field(max_length=9, description="Dimension API names to check for addition."),
    ],
    dimension_filter: Annotated[
        list[GoogleAnalyticsFieldFilter] | None,
        Field(description="Dimension filters included in the proposed report."),
    ] = None,
    metric_filter: Annotated[
        list[GoogleAnalyticsFieldFilter] | None,
        Field(description="Metric filters included in the proposed report."),
    ] = None,
) -> dict[str, Any]:
    request = _validated_request(
        metrics=metrics,
        dimensions=dimensions,
        candidate_metrics=candidate_metrics,
        candidate_dimensions=candidate_dimensions,
        dimension_filter=dimension_filter,
        metric_filter=metric_filter,
    )

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> Any:
            client = await google_analytics_client(ctx, entry)
            result = await check_report_fields(
                client,
                property_id=entry.external_id,
                request=request,
            )
            return IntegrationAuditOutcome(
                result,
                operation_detail=read_operation_detail(
                    entry,
                    operation="check_report_fields",
                    fields={
                        "metric_count": len(request.metrics),
                        "dimension_count": len(request.dimensions),
                        "candidate_metric_count": len(request.candidate_metrics),
                        "candidate_dimension_count": len(request.candidate_dimensions),
                        "compatible": bool(result["compatible"]),
                    },
                ),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_analytics_check_report_fields",
            operation="check_report_fields",
            execute=execute,
        )

    results = await run_context_fan_out(ctx, binding=GOOGLE_ANALYTICS_BINDING, operation=operation)
    return {"results": serialize_fan_out_results(results)}


def _validated_request(**values: Any) -> GoogleAnalyticsCheckReportFieldsInput:
    validate_field_selection(values["metrics"], values["dimensions"], require_metric=False)
    validate_field_selection(
        values["candidate_metrics"],
        values["candidate_dimensions"],
        require_metric=False,
    )
    validate_filter_kinds(values["dimension_filter"], metric=False)
    validate_filter_kinds(values["metric_filter"], metric=True)
    try:
        return GoogleAnalyticsCheckReportFieldsInput.model_validate(values)
    except ValidationError as exc:
        message = exc.errors(include_url=False)[0]["msg"]
        raise ModelRetry(
            f"Correct the Google Analytics field compatibility request: {message}."
        ) from exc


DEFINITION = RuntimeToolDefinition(
    name="google_analytics_check_report_fields",
    function=google_analytics_check_report_fields,
    description=(
        "Check which candidate dimension and metric API names can be added to an already-compatible "
        "Google Analytics standard report. This does not check realtime-report compatibility. "
        "Results are per selected property because custom-field compatibility can differ. Each "
        "result includes compatible, per-candidate compatibility, and incompatible_fields."
    ),
    provider="google_analytics",
    label="Check Google Analytics Report Fields",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    timeout=30,
    output_model=GoogleAnalyticsCheckReportFieldsOutput,
    integration_binding=GOOGLE_ANALYTICS_BINDING,
    availability_check=google_analytics_available,
    presentation=ToolPresentation(
        icon="google_analytics",
        running_label="Checking Google Analytics Report Fields",
        completed_label="Checked Google Analytics Report Fields",
        failed_label="Couldn't Check Google Analytics Report Fields",
        arg_fields=(
            ToolFieldPresentation(
                key="metrics",
                label="Current Metrics",
                format="list",
                editable=True,
            ),
            ToolFieldPresentation(
                key="dimensions",
                label="Current Dimensions",
                format="list",
                editable=True,
            ),
            ToolFieldPresentation(
                key="candidate_metrics",
                label="Candidate Metrics",
                format="list",
                editable=True,
            ),
            ToolFieldPresentation(
                key="candidate_dimensions",
                label="Candidate Dimensions",
                format="list",
                editable=True,
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
