# apps/api/integrations/google_ads/tools/link_negative_keyword_list.py

"""Approval-only negative keyword list campaign-link mutation tool."""

from collections.abc import Sequence
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.references import (
    GoogleAdsCampaignReference,
    GoogleAdsSharedSetReference,
)
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
    AuditStatus,
    IntegrationOperationChange,
    IntegrationOperationCounts,
    IntegrationOperationDetail,
    IntegrationOperationTarget,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import ScopedEntityReference

from ..operations.link_negative_keyword_list import link_negative_keyword_list
from ..operations.list_shared_sets import list_shared_sets
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
    verify_campaigns,
)


async def google_ads_link_negative_keyword_list(
    ctx: RunContext[RuntimeDeps],
    negative_list: Annotated[
        GoogleAdsSharedSetReference,
        Field(description="Negative keyword list to apply or remove."),
    ],
    campaign_ids: Annotated[
        list[GoogleAdsCampaignReference],
        Field(min_length=1, max_length=50, description="Campaigns to update."),
    ],
    action: Annotated[
        Literal["LINK", "UNLINK"],
        Field(description="Whether to apply or remove the list."),
    ],
) -> dict[str, Any]:
    if not campaign_ids:
        raise ModelRetry("Choose at least one Google Ads campaign.")
    if len(campaign_ids) > 50:
        raise ModelRetry("Choose at most 50 Google Ads campaigns per call.")
    resource_ids = {
        negative_list.integration_resource_id,
        *(campaign.integration_resource_id for campaign in campaign_ids),
    }
    if len(resource_ids) != 1:
        raise ModelRetry(
            "The negative keyword list and campaigns must belong to the same Google Ads account. "
            "Ask the user to choose them again."
        )

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[ScopedEntityReference],
    ) -> Any:
        list_references = [
            reference
            for reference in references
            if isinstance(reference, GoogleAdsSharedSetReference)
        ]
        campaign_references = [
            reference
            for reference in references
            if isinstance(reference, GoogleAdsCampaignReference)
        ]
        if len(list_references) != 1 or len(campaign_references) != len(campaign_ids):
            raise ModelRetry("Choose one negative keyword list and its campaigns again.")
        list_reference = list_references[0]
        normalized_campaign_ids = sorted(
            {reference.external_id for reference in campaign_references}
        )

        async def execute() -> Any:
            if not list_reference.external_id.isdigit() or any(
                not campaign_id.isdigit() for campaign_id in normalized_campaign_ids
            ):
                raise ModelRetry("A selected Google Ads reference is invalid.")
            client = await google_ads_client(ctx, entry)
            shared_sets = await list_shared_sets(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                shared_set_type="NEGATIVE_KEYWORDS",
                shared_set_ids=(list_reference.external_id,),
                limit=1,
            )
            if not any(
                str(shared_set.get("id", "")) == list_reference.external_id
                for shared_set in shared_sets
            ):
                raise ModelRetry(
                    "The selected negative keyword list is unavailable. "
                    "Ask the user to choose it again."
                )
            await verify_campaigns(
                client,
                entry=entry,
                campaign_ids=normalized_campaign_ids,
                ignore_removed=True,
            )
            return await link_negative_keyword_list(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                shared_set_id=list_reference.external_id,
                campaign_ids=normalized_campaign_ids,
                action=action,
            )

        return await run_audited_operation(
            ctx,
            entry,
            tool_name="google_ads_link_negative_keyword_list",
            operation="link_negative_keyword_list",
            execute=execute,
            external_ref_from_result=lambda value: ",".join(value["resource_names"]) or None,
            operation_detail_from_result=lambda value: _operation_detail(
                list_reference, campaign_references, action, value
            ),
            status_from_result=_audit_status,
            pending_operation_detail=_pending_operation_detail(
                list_reference, campaign_references, action
            ),
            require_durable_audit=True,
        )

    async def audit_write_denied(entry: ResolvedContextEntry) -> None:
        await record_google_ads_operation_audit(
            ctx,
            entry,
            tool_name="google_ads_link_negative_keyword_list",
            operation="link_negative_keyword_list",
            status=AuditStatus.FAILURE,
            error_code="write_not_permitted",
        )

    results = await run_context_targets(
        ctx.deps,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[negative_list, *campaign_ids],
        operation=operation,
        write=True,
        on_write_denied=audit_write_denied,
    )
    return {"results": [fan_out_dict(item) for item in results]}


def _audit_status(result: dict[str, Any]) -> AuditStatus:
    if result["campaign_errors"] and not result["resource_names"]:
        return AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _operation_detail(
    negative_list: GoogleAdsSharedSetReference,
    campaigns: Sequence[GoogleAdsCampaignReference],
    action: Literal["LINK", "UNLINK"],
    result: dict[str, Any],
) -> IntegrationOperationDetail:
    by_id = {campaign.external_id: campaign for campaign in campaigns}
    return IntegrationOperationDetail(
        target=_operation_target(negative_list),
        changes=[
            IntegrationOperationChange(
                action="link" if action == "LINK" else "unlink",
                entity_type="google_ads_campaign",
                external_ref=resource_name,
                fields={
                    "campaign_id": campaign_id,
                    "campaign_name": by_id.get(campaign_id).label if campaign_id in by_id else None,
                },
            )
            for resource_name in result["resource_names"]
            if (campaign_id := _campaign_id_from_link_resource(resource_name))
        ],
        counts=IntegrationOperationCounts(
            applied=len(result["resource_names"]),
            skipped=len(result.get("skipped_existing", result.get("not_found", []))),
            failed=len(result["campaign_errors"]),
        ),
    )


def _pending_operation_detail(
    negative_list: GoogleAdsSharedSetReference,
    campaigns: Sequence[GoogleAdsCampaignReference],
    action: Literal["LINK", "UNLINK"],
) -> IntegrationOperationDetail:
    return IntegrationOperationDetail(
        target=_operation_target(negative_list),
        changes=[
            IntegrationOperationChange(
                action="link" if action == "LINK" else "unlink",
                entity_type="google_ads_campaign",
                fields={"campaign_id": campaign.external_id, "campaign_name": campaign.label},
            )
            for campaign in campaigns
        ],
        counts=IntegrationOperationCounts(applied=0, skipped=0, failed=0),
    )


def _operation_target(
    reference: GoogleAdsSharedSetReference,
) -> IntegrationOperationTarget:
    return IntegrationOperationTarget(
        entity_type=reference.entity_kind,
        external_id=reference.external_id,
        display_name=reference.label,
        integration_resource_id=str(reference.integration_resource_id),
        attributes={"member_count": reference.member_count},
    )


def _campaign_id_from_link_resource(resource_name: str) -> str:
    return resource_name.rsplit("/", 1)[-1].split("~", 1)[0]


DEFINITION = RuntimeToolDefinition(
    name="google_ads_link_negative_keyword_list",
    function=google_ads_link_negative_keyword_list,
    description="Apply or remove a negative keyword list across selected campaigns.",
    provider="google_ads",
    label="Apply Google Ads Negative Keyword List",
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
        running_label="Updating Negative Keyword List Campaigns",
        completed_label="Updated Negative Keyword List Campaigns",
        failed_label="Couldn't Update Negative Keyword List Campaigns",
        approval_title="Apply Negative Keyword List",
        approval_prompt=(
            "The agent wants to change which campaigns this negative keyword list applies to."
        ),
        approve_label="Approve & Apply",
        arg_fields=(
            ToolFieldPresentation(
                key="negative_list",
                label="Negative Keyword List",
                format="entity",
                editable=True,
                entity_kind="google_ads_shared_set",
            ),
            ToolFieldPresentation(
                key="campaign_ids",
                label="Campaigns",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_campaign",
            ),
            ToolFieldPresentation(
                key="action",
                label="Action",
                editable=True,
                options=("LINK", "UNLINK"),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
