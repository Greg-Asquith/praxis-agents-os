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
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.update_campaign_status import update_campaign_status
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.mutation_evidence import audit_status, terminal_operation_detail
from .verifiers import verify_campaigns


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
        references_by_id: dict[str, GoogleAdsCampaignReference] = {}
        for reference in references:
            references_by_id.setdefault(reference.external_id, reference)
        normalized_references = [
            references_by_id[campaign_id] for campaign_id in sorted(references_by_id)
        ]
        normalized_ids = [reference.external_id for reference in normalized_references]
        pending_detail = _pending_operation_detail(entry, normalized_references, status)

        async def execute() -> Any:
            client = await google_ads_client(ctx, entry)
            if any(not campaign_id.isdigit() for campaign_id in normalized_ids):
                raise ModelRetry("A selected Google Ads campaign reference is invalid.")
            await verify_campaigns(
                client,
                entry=entry,
                campaign_ids=normalized_ids,
                ignore_removed=True,
            )
            ledger = await update_campaign_status(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                campaign_ids=normalized_ids,
                status=status,
            )
            result = ledger.result()
            operation_detail = terminal_operation_detail(pending_detail, ledger)
            return IntegrationAuditOutcome(
                result,
                status=audit_status(operation_detail),
                external_ref=",".join(result["resource_names"]) or None,
                operation_detail=operation_detail,
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_campaign_status",
            operation="update_campaign_status",
            execute=execute,
            pending_operation_detail=pending_detail,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=campaign_ids,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    campaigns: list[GoogleAdsCampaignReference],
    status: Literal["ENABLED", "PAUSED"],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key="campaigns:update-status",
                action="update_status",
                entity_type="google_ads_campaign",
                fields={"status": status},
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "campaign_id": campaign.external_id,
                            "campaign_name": campaign.label,
                        }
                    )
                    for campaign in campaigns
                ],
            )
        ],
    )


def _account_target(entry: ResolvedContextEntry) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type="google_ads_account",
        external_id=entry.external_id,
        display_name=entry.display_name,
        integration_resource_id=str(entry.integration_resource_id),
    )


def _campaign_id_from_resource(resource_name: str) -> str:
    return resource_name.rsplit("/", 1)[-1]


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_campaign_status",
    function=google_ads_update_campaign_status,
    description="Pause or enable named campaigns in selected Google Ads accounts.",
    provider="google_ads",
    label="Update Google Ads Campaign Status",
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
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
