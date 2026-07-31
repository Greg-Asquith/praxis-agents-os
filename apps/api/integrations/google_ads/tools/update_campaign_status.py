# apps/api/integrations/google_ads/tools/update_campaign_status.py

"""Approval-only Google Ads campaign status mutation runtime tool."""

from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.references import GoogleAdsCampaignReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets

from ..operations.update_campaign_status import update_campaign_status
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    fan_out_dict,
    google_ads_available,
    google_ads_client,
    login_customer_id,
    record_google_ads_operation_audit,
    run_audited_operation,
)


async def google_ads_update_campaign_status(
    ctx: RunContext[RuntimeDeps],
    campaign_ids: Annotated[
        list[GoogleAdsCampaignReference],
        Field(min_length=1, max_length=50, description="Scoped campaigns to update."),
    ],
    status: Annotated[
        Literal["ENABLED", "PAUSED"],
        Field(description="New campaign serving status."),
    ],
) -> dict[str, Any]:
    if not campaign_ids:
        raise ModelRetry("google_ads_update_campaign_status requires campaigns.")

    async def operation(
        entry: ResolvedContextEntry,
        references: list[GoogleAdsCampaignReference],
    ) -> Any:
        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            normalized_ids = sorted({reference.external_id for reference in references})
            if any(not campaign_id.isdigit() for campaign_id in normalized_ids):
                raise ModelRetry("A selected Google Ads campaign reference is invalid.")
            lookup_query = (
                "SELECT campaign.id, campaign.name, campaign.status FROM campaign "  # noqa: S608 -- digit-only ids
                f"WHERE campaign.id IN ({', '.join(normalized_ids)}) "
                f"LIMIT {len(normalized_ids)}"
            )
            lookup = await client.post(
                f"customers/{entry.external_id}/googleAds:searchStream",
                operation="resolve_campaign_references",
                login_customer_id=login_customer_id(entry),
                json={"query": lookup_query},
            )
            from integrations.google_ads.operations.utils import stream_rows

            resolved_ids = {
                str(campaign.get("id", ""))
                for row in stream_rows(lookup)
                if isinstance((campaign := row.get("campaign")), dict)
            }
            if resolved_ids != set(normalized_ids):
                raise ModelRetry(
                    "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
                )
            return await update_campaign_status(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                campaign_ids=normalized_ids,
                status=status,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="google_ads_update_campaign_status",
            operation="update_campaign_status",
            execute=execute,
            external_ref_from_result=lambda value: ",".join(value["resource_names"]) or None,
        )

    async def audit_write_denied(entry: ResolvedContextEntry) -> None:
        await record_google_ads_operation_audit(
            ctx,
            entry,
            tool_name="google_ads_update_campaign_status",
            operation="update_campaign_status",
            status=AuditStatus.FAILURE,
            error_code="write_not_permitted",
        )

    results = await run_context_targets(
        ctx.deps,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=campaign_ids,
        operation=operation,
        write=True,
        on_write_denied=audit_write_denied,
    )
    return {"results": [fan_out_dict(item) for item in results]}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_campaign_status",
    function=google_ads_update_campaign_status,
    description="Pause or enable named campaigns in selected Google Ads accounts.",
    provider="google_ads",
    label="Update Google Ads Campaign Status",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Google Ads Campaigns",
        completed_label="Updated Google Ads Campaigns",
        failed_label="Couldn't Update Google Ads Campaigns",
        approval_title="Update Google Ads Campaign Status",
        approval_prompt="The agent wants to change campaign serving status.",
        approve_label="Approve & Update",
        arg_fields=(
            ToolFieldPresentation(
                key="campaign_ids",
                label="Campaigns",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_campaign",
            ),
            ToolFieldPresentation(
                key="status",
                label="Status",
                editable=True,
                options=("ENABLED", "PAUSED"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
