# apps/api/integrations/google_ads/tools/get_report_field.py

"""Get Google Ads report field runtime tool."""

from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.integration import IntegrationNotFoundError
from integrations.google_ads.client import GOOGLE_ADS_API_VERSION
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.get_report_field import get_report_field, validate_report_field_name
from .schemas import GoogleAdsGetReportFieldOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    active_google_ads_entries,
    google_ads_available,
    google_ads_client,
)


async def google_ads_get_report_field(
    ctx: RunContext[RuntimeDeps],
    field_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            description=(
                "Exact GAQL resource or dotted field name, such as campaign or metrics.clicks."
            ),
        ),
    ],
) -> dict[str, Any]:
    """Returns bounded metadata for one exact GAQL resource or field."""
    try:
        normalized_name = validate_report_field_name(field_name)
    except (TypeError, ValueError) as exc:
        raise ModelRetry(str(exc)) from exc

    entry = active_google_ads_entries(ctx)[0]

    async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
        client = await google_ads_client(ctx, entry)
        result = await get_report_field(client, field_name=normalized_name)
        return IntegrationAuditOutcome(result)

    try:
        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_get_report_field",
            operation="get_report_field",
            execute=execute,
        )
    except IntegrationNotFoundError as exc:
        raise ModelRetry(
            f"Google Ads has no report field named {normalized_name}. Use "
            "google_ads_list_report_fields to find the exact resource, metric, or segment name."
        ) from exc


DEFINITION = RuntimeToolDefinition(
    name="google_ads_get_report_field",
    function=google_ads_get_report_field,
    description=(
        f"Get exact Google Ads {GOOGLE_ADS_API_VERSION} metadata for one GAQL resource or field, "
        "including enum values and selectable-with compatibility. Use the result to construct a "
        "query, then call google_ads_run_report to execute it."
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
        arg_fields=(ToolFieldPresentation(key="field_name", label="Field Name"),),
        result_fields=(
            ToolFieldPresentation(key="name", label="Field Name"),
            ToolFieldPresentation(key="category", label="Category"),
            ToolFieldPresentation(key="data_type", label="Data Type"),
            ToolFieldPresentation(key="enum_values", label="Enum Values", format="list"),
            ToolFieldPresentation(
                key="selectable_with",
                label="Selectable With",
                format="list",
            ),
        ),
    ),
)
