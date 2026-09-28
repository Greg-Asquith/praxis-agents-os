# apps/api/integrations/meta_ads/tools/list_activities.py

"""List recent changes in selected Meta ad accounts."""

from typing import Annotated, Any

from pydantic import Field, ValidationError
from pydantic_ai import RunContext

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
from services.integrations.report_results import REPORT_RESULT_GUIDANCE, ReportResultBudget
from utils.metadata import metadata_str

from ..operations.list_activities import list_activities
from ..throttle import ensure_account_available
from .schemas.activities import MetaAdsActivitiesInput, MetaAdsActivitiesOutput
from .schemas.base import MetaAdsId
from .utils.audit import activities_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client
from .utils.validation import absolute_date, validation_retry


async def meta_ads_list_activities(
    ctx: RunContext[RuntimeDeps],
    since: Annotated[str, Field(description="Start date as YYYY-MM-DD in the account time zone.")],
    until: Annotated[str, Field(description="End date as YYYY-MM-DD in the account time zone.")],
    object_ids: Annotated[list[MetaAdsId] | None, Field(min_length=1, max_length=50)] = None,
) -> dict[str, Any]:
    try:
        request = MetaAdsActivitiesInput(
            since=absolute_date(since, "since"),
            until=absolute_date(until, "until"),
            object_ids=object_ids,
        )
    except ValidationError as exc:
        raise validation_retry(exc) from None
    budget = ReportResultBudget("meta_ads", "list_activities")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            ensure_account_available(entry.external_id, operation="list_activities")
            client = await meta_ads_client(ctx, entry)
            result = await list_activities(
                client,
                account_id=entry.external_id,
                request=request,
                timezone_name=metadata_str(entry.permissions_metadata.get("timezone_name")) or "",
                max_response_bytes=budget.remaining,
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=activities_audit_detail(entry.external_id, request, result),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_list_activities",
            operation="list_activities",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx, binding=META_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_list_activities",
    function=meta_ads_list_activities,
    description=(
        "List recent changes in every Meta ad account selected in Active Context: what changed, "
        "which object, who made the change, and when. Use absolute since and until dates in "
        "the account time zone, covering at most 31 days; data.timezone_name names the zone "
        "used, which is UTC when the account time zone is unknown. object_ids keeps changes to "
        "those campaign, ad set, or ad IDs. event_time is ISO 8601 with an offset. old_value and "
        "new_value hold Meta's simple before and after values when supplied, as unconverted "
        "text; amounts can be in minor currency units. Returns at most 200 events per account; "
        "inspect truncated and window_note before treating the history as complete."
    )
    + REPORT_RESULT_GUIDANCE,
    provider="meta_ads",
    label="List Meta Ads changes",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsActivitiesOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    preview_list_path="results.*.data.events",
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Listing Meta Ads changes",
        completed_label="Listed Meta Ads changes",
        failed_label="Couldn't list Meta Ads changes",
        arg_fields=(
            ToolFieldPresentation(key="since", label="Start date"),
            ToolFieldPresentation(key="until", label="End date"),
            ToolFieldPresentation(
                key="object_ids", label="Object IDs", format="list", secondary=True
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
