# apps/api/integrations/meta_ads/tools/list_assets.py

"""List the Pages, Instagram accounts, and media each selected ad account can use in ads."""

from typing import Annotated, Any

from pydantic import Field
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

from ..operations.list_assets import ASSET_KINDS, list_assets
from ..throttle import ensure_account_available
from .schemas.assets import MetaAdsAssetKind, MetaAdsAssetsOutput
from .utils.audit import assets_audit_detail
from .utils.bindings import META_ADS_BINDING, RESULTS_FIELD
from .utils.client import meta_ads_available, meta_ads_client


async def meta_ads_list_assets(
    ctx: RunContext[RuntimeDeps],
    kinds: Annotated[
        list[MetaAdsAssetKind] | None,
        Field(min_length=1, max_length=4, description="Asset kinds to list; all by default."),
    ] = None,
) -> dict[str, Any]:
    requested = tuple(kind for kind in ASSET_KINDS if kinds is None or kind in kinds)
    budget = ReportResultBudget("meta_ads", "list_assets")

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            ensure_account_available(entry.external_id, operation="list_assets")
            client = await meta_ads_client(ctx, entry)
            result = await list_assets(
                client,
                account_id=entry.external_id,
                scope_label=entry.display_name,
                kinds=requested,
                max_response_bytes=budget.remaining,
            )
            return IntegrationAuditOutcome(
                result.model_dump(mode="json"),
                operation_detail=assets_audit_detail(entry.external_id, requested, result),
            )

        return await run_audited_integration_operation(
            ctx, entry, tool_name="meta_ads_list_assets", operation="list_assets", execute=execute
        )

    results = await run_context_fan_out(
        ctx, binding=META_ADS_BINDING, operation=operation, result_budget=budget
    )
    return {"results": serialize_fan_out_results(results)}


DEFINITION = RuntimeToolDefinition(
    name="meta_ads_list_assets",
    function=meta_ads_list_assets,
    description=(
        "List what each Meta ad account selected in Active Context can use in new ads: the "
        "Facebook Pages it can advertise as, its connected Instagram accounts, and up to 50 "
        "images and 50 videos from its media library. Each item is a reference to pass to ad "
        "creation as is. Use kinds to list only some of pages, instagram_accounts, images, and "
        "videos. A video can go in an ad only when its media_status is ready. truncated names "
        "kinds with more items than returned; notes explain kinds Meta didn't allow reading."
    )
    + REPORT_RESULT_GUIDANCE,
    provider="meta_ads",
    label="List Meta Ads Pages and Media",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=MetaAdsAssetsOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    integration_binding=META_ADS_BINDING,
    availability_check=meta_ads_available,
    presentation=ToolPresentation(
        icon="meta_ads",
        running_label="Listing Meta Ads Pages and Media",
        completed_label="Listed Meta Ads Pages and Media",
        failed_label="Couldn't List Meta Ads Pages and Media",
        arg_fields=(ToolFieldPresentation(key="kinds", label="Kinds", format="list"),),
        result_fields=RESULTS_FIELD,
    ),
)
