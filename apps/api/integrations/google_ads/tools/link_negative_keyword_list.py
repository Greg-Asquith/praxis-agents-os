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
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.entity_references import ScopedEntityReference
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.link_negative_keyword_list import link_negative_keyword_list
from .schemas import GoogleAdsOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .verifiers import verify_campaigns, verify_shared_sets

_CONTRADICTORY_ACCOUNTING_MESSAGE = "Google Ads returned contradictory campaign link accounting"


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
            await verify_shared_sets(
                client,
                entry=entry,
                shared_set_ids=(list_reference.external_id,),
            )
            await verify_campaigns(
                client,
                entry=entry,
                campaign_ids=normalized_campaign_ids,
                ignore_removed=True,
            )
            ledger = await link_negative_keyword_list(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                shared_set_id=list_reference.external_id,
                campaign_ids=normalized_campaign_ids,
                action=action,
            )
            ledger.require_verified()
            result = ledger.result()
            return IntegrationAuditOutcome(
                result,
                status=_audit_status(result),
                external_ref=",".join(result["resource_names"]) or None,
                operation_detail=_operation_detail(
                    list_reference, campaign_references, action, result
                ),
            )

        audited_result = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_link_negative_keyword_list",
            operation="link_negative_keyword_list",
            execute=execute,
            pending_operation_detail=_pending_operation_detail(
                list_reference, campaign_references, action
            ),
        )
        return _campaign_link_result(
            list_reference,
            campaign_references,
            action,
            audited_result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[negative_list, *campaign_ids],
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _audit_status(result: dict[str, Any]) -> AuditStatus:
    if result["campaign_errors"] and not result["resource_names"]:
        return AuditStatus.FAILURE
    return AuditStatus.SUCCESS


def _campaign_link_result(
    negative_list: GoogleAdsSharedSetReference,
    campaigns: Sequence[GoogleAdsCampaignReference],
    action: Literal["LINK", "UNLINK"],
    result: dict[str, Any],
) -> dict[str, Any]:
    requested_by_id = {campaign.external_id: campaign for campaign in campaigns}
    if len(requested_by_id) != len(campaigns):
        raise ValueError("Google Ads campaign references must be unique")

    applied_by_id: dict[str, str] = {}
    for resource_name in result["resource_names"]:
        campaign_id = _campaign_id_from_link_resource(resource_name)
        if campaign_id not in requested_by_id or campaign_id in applied_by_id:
            raise ValueError(_CONTRADICTORY_ACCOUNTING_MESSAGE)
        applied_by_id[campaign_id] = resource_name

    skipped_key = "skipped_existing" if action == "LINK" else "not_found"
    skipped_ids = result[skipped_key]
    if len(set(skipped_ids)) != len(skipped_ids) or any(
        campaign_id not in requested_by_id for campaign_id in skipped_ids
    ):
        raise ValueError(_CONTRADICTORY_ACCOUNTING_MESSAGE)

    errors_by_id: dict[str, dict[str, str]] = {}
    for error in result["campaign_errors"]:
        campaign_id = error["campaign_id"]
        if campaign_id not in requested_by_id or campaign_id in errors_by_id:
            raise ValueError(_CONTRADICTORY_ACCOUNTING_MESSAGE)
        errors_by_id[campaign_id] = error

    accounted_ids = set(applied_by_id) | set(skipped_ids) | set(errors_by_id)
    if len(accounted_ids) != len(applied_by_id) + len(skipped_ids) + len(
        errors_by_id
    ) or accounted_ids != set(requested_by_id):
        raise ValueError(_CONTRADICTORY_ACCOUNTING_MESSAGE)

    applied_outcome = "linked" if action == "LINK" else "unlinked"
    skipped_outcome = "already_linked" if action == "LINK" else "not_linked"
    campaign_results: list[dict[str, Any]] = []
    for campaign in campaigns:
        campaign_id = campaign.external_id
        row: dict[str, Any] = {
            "campaign_id": campaign_id,
            "campaign_name": campaign.label,
            "outcome": (
                applied_outcome
                if campaign_id in applied_by_id
                else skipped_outcome
                if campaign_id in skipped_ids
                else "failed"
            ),
            "external_ref": applied_by_id.get(campaign_id),
        }
        if error := errors_by_id.get(campaign_id):
            row.update(message=error["message"], error_code=error["error_code"])
        campaign_results.append(row)

    return {
        **result,
        "action": action,
        "negative_list": {
            "external_id": negative_list.external_id,
            "name": negative_list.label,
            "member_count": negative_list.member_count,
        },
        "campaigns": campaign_results,
    }


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
