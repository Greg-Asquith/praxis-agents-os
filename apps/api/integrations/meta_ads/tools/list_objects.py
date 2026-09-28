# apps/api/integrations/meta_ads/tools/list_objects.py

"""List selected accounts' campaigns, ad sets and ads."""

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

from ..operations.list_objects import list_objects
from ..throttle import ensure_account_available
from .schemas.base import MetaAdsId
from .schemas.objects import (
    MetaAdsAdStatus,
    MetaAdsObjectsInput,
    MetaAdsObjectsOutput,
    MetaAdsObjectType,
)
from .utils.audit import objects_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client
from .utils.validation import validation_retry


async def meta_ads_list_objects(
    ctx: RunContext[RuntimeDeps],
    object_type: MetaAdsObjectType,
    statuses: Annotated[list[MetaAdsAdStatus] | None, Field(min_length=1, max_length=12)] = None,
    campaign_ids: Annotated[list[MetaAdsId] | None, Field(min_length=1, max_length=50)] = None,
    adset_ids: Annotated[list[MetaAdsId] | None, Field(min_length=1, max_length=50)] = None,
    name_contains: Annotated[str | None, Field(min_length=1, max_length=512)] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    try:
        request = MetaAdsObjectsInput(
            object_type=object_type,
            statuses=statuses,
            campaign_ids=campaign_ids,
            adset_ids=adset_ids,
            name_contains=name_contains,
            limit=limit,
        )
    except ValidationError as exc:
        raise validation_retry(exc) from None
    budget = ReportResultBudget("meta_ads", "list_objects")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            ensure_account_available(entry.external_id, operation="list_objects")
            client = await meta_ads_client(ctx, entry)
            result = await list_objects(
                client,
                account_id=entry.external_id,
                **request.model_dump(),
                currency=metadata_str(entry.permissions_metadata.get("currency")) or "",
                max_response_bytes=budget.remaining,
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=objects_audit_detail(entry.external_id, request, result),
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="meta_ads_list_objects",
            operation="list_objects",
            execute=execute,
        )

    results = await run_context_fan_out(
        ctx, binding=META_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_list_objects",
    function=meta_ads_list_objects,
    description=(
        "List campaigns, ad sets or ads in every Meta ad account selected in Active Context. "
        "Defaults to active and paused objects, including paused parent campaigns and ad sets. "
        "Use statuses to request other delivery states, campaign_ids to filter ad sets or ads, "
        "adset_ids to filter ads, and name_contains for a name substring. Parent IDs are digits only. "
        "Budgets and bids use exact decimal strings in major units of data.currency; a campaign "
        "budget kind means the parent campaign holds an ad set's budget. Ad budgets are null. "
        "limit defaults to 100, at most 500 objects and 10 pages per account. Inspect truncated "
        "before treating returned objects as complete."
    )
    + REPORT_RESULT_GUIDANCE,
    provider="meta_ads",
    label="List Meta Ads objects",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsObjectsOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    preview_list_path="results.*.data.objects",
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Listing Meta Ads objects",
        completed_label="Listed Meta Ads objects",
        failed_label="Couldn't list Meta Ads objects",
        arg_fields=(
            ToolFieldPresentation(key="object_type", label="Object type"),
            ToolFieldPresentation(key="statuses", label="Delivery statuses", format="list"),
            ToolFieldPresentation(
                key="campaign_ids", label="Campaign IDs", format="list", secondary=True
            ),
            ToolFieldPresentation(
                key="adset_ids", label="Ad set IDs", format="list", secondary=True
            ),
            ToolFieldPresentation(key="name_contains", label="Name contains", secondary=True),
            ToolFieldPresentation(key="limit", label="Maximum objects", secondary=True),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
