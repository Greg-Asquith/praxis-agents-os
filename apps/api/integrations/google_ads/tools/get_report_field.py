# apps/api/integrations/google_ads/tools/get_report_field.py

"""Get Google Ads report field runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.client import GOOGLE_ADS_API_VERSION
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_report_field import (
    REPORT_FIELD_BATCH_LIMIT,
    get_report_fields,
    validate_report_field_names,
)
from .schemas import GoogleAdsGetReportFieldOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    active_google_ads_entries,
    google_ads_available,
    google_ads_client,
)


async def google_ads_get_report_field(
    ctx: RunContext[RuntimeDeps],
    field_names: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=256)]],
        Field(
            min_length=1,
            max_length=REPORT_FIELD_BATCH_LIMIT,
            description=(
                "Every exact GAQL resource or dotted field name to inspect, such as campaign or "
                "metrics.clicks. Pass all names in one call."
            ),
        ),
    ],
) -> dict[str, Any]:
    """Returns bounded metadata for a batch of exact GAQL resources or fields."""
    try:
        normalized_names = validate_report_field_names(field_names)
    except (TypeError, ValueError) as exc:
        raise ModelRetry(str(exc)) from exc

    entry = active_google_ads_entries(ctx)[0]

    async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
        client = await google_ads_client(ctx, entry)
        result = await get_report_fields(client, field_names=normalized_names)
        return IntegrationAuditOutcome(result)

    return await run_audited_integration_operation(
        ctx,
        entry,
        tool_name="google_ads_get_report_field",
        operation="get_report_field",
        execute=execute,
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_get_report_field",
    function=google_ads_get_report_field,
    description=(
        f"Get exact Google Ads {GOOGLE_ADS_API_VERSION} metadata for up to "
        f"{REPORT_FIELD_BATCH_LIMIT} GAQL resources or fields in one call, including enum values "
        "and selectable-with compatibility. Pass every name you want to check in a single "
        "field_names list. Names Google Ads does not know come back in `missing` instead of "
        "failing, so never look names up one at a time. Only needed for enum values or "
        "compatibility that google_ads_list_report_fields did not already answer. Use the result "
        "to construct a query, then call google_ads_run_report to execute it."
    ),
    provider="google_ads",
    label="Get Google Ads Report Field",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=False,
    timeout=30,
    output_model=GoogleAdsGetReportFieldOutput,
    configurable=False,
    auto_mount=True,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Getting Google Ads Report Field",
        completed_label="Got Google Ads Report Field",
        failed_label="Couldn't Get Google Ads Report Field",
        arg_fields=(ToolFieldPresentation(key="field_names", label="Field Names", format="list"),),
        result_fields=(
            ToolFieldPresentation(
                key="fields",
                label="Fields",
                format="records",
                columns=(
                    ToolFieldColumn(key="name", label="Field Name"),
                    ToolFieldColumn(key="category", label="Category"),
                    ToolFieldColumn(key="data_type", label="Data Type"),
                    ToolFieldColumn(key="enum_values", label="Enum Values", format="list"),
                    ToolFieldColumn(key="selectable_with", label="Selectable With", format="list"),
                ),
            ),
            ToolFieldPresentation(key="missing", label="Not Found", format="list"),
        ),
    ),
)
