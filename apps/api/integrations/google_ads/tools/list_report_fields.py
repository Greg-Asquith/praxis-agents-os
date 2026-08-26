# apps/api/integrations/google_ads/tools/list_report_fields.py

"""List Google Ads report fields runtime tool."""

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
    ToolFieldPresentation,
    ToolPresentation,
)
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.list_report_fields import (
    list_report_fields,
    normalize_report_field_search,
    validate_report_field_limit,
    validate_report_resource,
)
from .schemas import GoogleAdsListReportFieldsOutput
from .utils import (
    GOOGLE_ADS_BINDING,
    active_google_ads_entries,
    google_ads_available,
    google_ads_client,
)


async def google_ads_list_report_fields(
    ctx: RunContext[RuntimeDeps],
    resource: Annotated[
        str,
        Field(
            min_length=1,
            max_length=128,
            description="GAQL FROM resource name, such as campaign or search_term_view.",
        ),
    ],
    search: Annotated[
        str | None,
        Field(
            max_length=100,
            description="Optional text matched against resource fields, metrics, and segments.",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum matching fields, metrics, and segments returned per collection.",
        ),
    ] = 50,
) -> dict[str, Any]:
    """Returns bounded report fields and compatibility for one GAQL resource."""
    try:
        normalized_resource = validate_report_resource(resource)
        normalized_search = normalize_report_field_search(search)
        validate_report_field_limit(limit)
    except (TypeError, ValueError) as exc:
        raise ModelRetry(str(exc)) from exc

    entry = active_google_ads_entries(ctx)[0]

    async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
        client = await google_ads_client(ctx, entry)
        result = await list_report_fields(
            client,
            resource=normalized_resource,
            search=normalized_search,
            limit=limit,
        )
        return IntegrationAuditOutcome(result)

    return await run_audited_integration_operation(
        ctx,
        entry,
        tool_name="google_ads_list_report_fields",
        operation="list_report_fields",
        execute=execute,
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_list_report_fields",
    function=google_ads_list_report_fields,
    description=(
        f"List bounded Google Ads {GOOGLE_ADS_API_VERSION} attributes, compatible metrics, and "
        "compatible segments for one GAQL FROM resource. Use the returned names to construct a "
        "query, then call google_ads_run_report to execute it."
    ),
    provider="google_ads",
    label="List Google Ads Report Fields",
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    takes_ctx=True,
    default_policy=TOOL_POLICY_AUTO,
    supports_auto=True,
    supports_approval=False,
    timeout=30,
    output_model=GoogleAdsListReportFieldsOutput,
    configurable=False,
    auto_mount=True,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Listing Google Ads Report Fields",
        completed_label="Listed Google Ads Report Fields",
        failed_label="Couldn't List Google Ads Report Fields",
        arg_fields=(
            ToolFieldPresentation(key="resource", label="Resource"),
            ToolFieldPresentation(key="search", label="Search"),
            ToolFieldPresentation(key="limit", label="Limit", format="number"),
        ),
        result_fields=(
            ToolFieldPresentation(key="fields", label="Fields", format="list"),
            ToolFieldPresentation(key="metrics", label="Metrics", format="list"),
            ToolFieldPresentation(key="segments", label="Segments", format="list"),
        ),
    ),
)
