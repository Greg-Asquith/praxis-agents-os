# apps/api/integrations/google_ads/tools/update_device_bid_modifiers.py

"""Approval-only Google Ads device bid modifier runtime tool."""

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from integrations.google_ads.client import normalize_customer_id
from integrations.google_ads.operations.list_campaign_device_criteria import (
    GoogleAdsCampaignDeviceState,
)
from integrations.google_ads.operations.utils import rounded_bid_modifier
from integrations.google_ads.references import GoogleAdsCampaignReference
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..operations.update_device_bid_modifiers import update_device_bid_modifiers
from .schemas import GoogleAdsDeviceAdjustment, GoogleAdsDeviceBidModifierOutput
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    RESULTS_FIELD,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .verifiers import verify_campaigns_for_device_bidding

_IGNORED_NONZERO_STRATEGIES = {
    "TARGET_ROAS",
    "MAXIMIZE_CONVERSION_VALUE",
}


async def google_ads_update_device_bid_modifiers(
    ctx: RunContext[RuntimeDeps],
    campaign_ids: Annotated[
        list[GoogleAdsCampaignReference],
        Field(min_length=1, max_length=50, description="Scoped campaigns to update."),
    ],
    adjustments: Annotated[
        list[GoogleAdsDeviceAdjustment],
        Field(min_length=1, max_length=3, description="One row per device."),
    ],
) -> dict[str, Any]:
    _validate_args(campaign_ids, adjustments)
    normalized_adjustments = _normalize_adjustments(adjustments)

    async def operation(
        entry: ResolvedContextEntry,
        references: list[GoogleAdsCampaignReference],
    ) -> Any:
        references_by_id: dict[str, GoogleAdsCampaignReference] = {}
        for reference in references:
            references_by_id.setdefault(reference.campaign_id, reference)
        campaigns = [references_by_id[key] for key in sorted(references_by_id)]
        pending_detail = _pending_operation_detail(entry, campaigns, normalized_adjustments)
        campaign_state: dict[str, GoogleAdsCampaignDeviceState] = {}

        async def execute() -> Any:
            nonlocal campaign_state
            client = await google_ads_client(ctx, entry)
            campaign_state = await verify_campaigns_for_device_bidding(
                client,
                entry=entry,
                campaign_ids=[campaign.campaign_id for campaign in campaigns],
            )
            ledger = await update_device_bid_modifiers(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                adjustments=[
                    (campaign.campaign_id, adjustment.device, adjustment.bid_modifier)
                    for campaign in campaigns
                    for adjustment in normalized_adjustments
                ],
                existing_state=campaign_state,
            )
            result = ledger.result()
            operation_detail = terminal_operation_detail(pending_detail, ledger)
            return IntegrationAuditOutcome(
                result,
                status=audit_status(operation_detail),
                external_ref=",".join(result["resource_names"]) or None,
                operation_detail=operation_detail,
            )

        result = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_update_device_bid_modifiers",
            operation="update_device_bid_modifiers",
            execute=execute,
            pending_operation_detail=pending_detail,
        )
        return _device_bid_modifier_result(
            campaigns,
            normalized_adjustments,
            customer_id=entry.external_id,
            campaign_state=campaign_state,
            result=result,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=campaign_ids,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


def _validate_args(
    campaigns: Sequence[GoogleAdsCampaignReference],
    adjustments: Sequence[GoogleAdsDeviceAdjustment],
) -> None:
    if not campaigns:
        raise ModelRetry("Choose at least one Google Ads campaign.")
    if len(campaigns) > 50:
        raise ModelRetry("Choose at most 50 Google Ads campaigns per call.")
    if not adjustments:
        raise ModelRetry("Add at least one device bid adjustment.")
    if len(adjustments) > 3:
        raise ModelRetry("Add at most one adjustment for desktop, mobile, and tablet.")
    devices = [adjustment.device for adjustment in adjustments]
    if len(set(devices)) != len(devices):
        raise ModelRetry("Each device can appear only once. Remove duplicate device rows.")
    for adjustment in adjustments:
        value = adjustment.bid_modifier
        if value != 0 and not 0.1 <= value <= 10.0:
            raise ModelRetry(
                f"The {adjustment.device} bid modifier must be 0 or between 0.1 and 10.0."
            )


def _normalize_adjustments(
    adjustments: Sequence[GoogleAdsDeviceAdjustment],
) -> list[GoogleAdsDeviceAdjustment]:
    return sorted(
        (
            adjustment.model_copy(
                update={"bid_modifier": float(rounded_bid_modifier(adjustment.bid_modifier))}
            )
            for adjustment in adjustments
        ),
        key=lambda item: item.device,
    )


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    campaigns: list[GoogleAdsCampaignReference],
    adjustments: list[GoogleAdsDeviceAdjustment],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"campaigns:update-device-bid-modifier:{adjustment.device.lower()}",
                action="update_device_bid_modifier",
                entity_type="google_ads_campaign",
                fields={
                    "device": adjustment.device,
                    "bid_modifier": _modifier_text(adjustment.bid_modifier),
                },
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "campaign_id": campaign.campaign_id,
                            "device": adjustment.device,
                            "bid_modifier": _modifier_text(adjustment.bid_modifier),
                            "campaign_name": campaign.label,
                        }
                    )
                    for campaign in campaigns
                ],
            )
            for adjustment in adjustments
        ],
    )


def _device_bid_modifier_result(
    campaigns: list[GoogleAdsCampaignReference],
    adjustments: list[GoogleAdsDeviceAdjustment],
    *,
    customer_id: str,
    campaign_state: Mapping[str, GoogleAdsCampaignDeviceState],
    result: dict[str, Any],
) -> dict[str, Any]:
    updated = {_outcome_key(item): item for item in result["updated"]}
    already_set = {_outcome_key(item): item for item in result["already_set"]}
    failed = {_outcome_key(item): item for item in result["device_errors"]}
    expected = {
        (campaign.campaign_id, adjustment.device)
        for campaign in campaigns
        for adjustment in adjustments
    }
    if set(updated) | set(already_set) | set(failed) != expected:
        raise ValueError("Google Ads returned contradictory device bid modifier accounting")

    return {
        "campaigns": [
            {
                "campaign_id": campaign.campaign_id,
                "campaign_name": campaign.label,
                "bidding_strategy_type": campaign_state[campaign.campaign_id][
                    "bidding_strategy_type"
                ],
                "target_cpa_configured": campaign_state[campaign.campaign_id][
                    "target_cpa_configured"
                ],
                "devices": [
                    _device_outcome(
                        campaign.campaign_id,
                        adjustment,
                        customer_id=customer_id,
                        campaign_state=campaign_state,
                        updated=updated,
                        already_set=already_set,
                        failed=failed,
                    )
                    for adjustment in adjustments
                ],
            }
            for campaign in campaigns
        ]
    }


def _device_outcome(
    campaign_id: str,
    adjustment: GoogleAdsDeviceAdjustment,
    *,
    customer_id: str,
    campaign_state: Mapping[str, GoogleAdsCampaignDeviceState],
    updated: Mapping[tuple[str, str], dict[str, Any]],
    already_set: Mapping[tuple[str, str], dict[str, Any]],
    failed: Mapping[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    key = (campaign_id, adjustment.device)
    existing = campaign_state[campaign_id]["devices"].get(adjustment.device)
    strategy = campaign_state[campaign_id]["bidding_strategy_type"]
    row: dict[str, Any] = {
        "device": adjustment.device,
        "requested_bid_modifier": adjustment.bid_modifier,
    }
    if existing is not None:
        row["previous_bid_modifier"] = existing["bid_modifier"]
    if note := _strategy_note(
        strategy,
        adjustment.bid_modifier,
        target_cpa_configured=campaign_state[campaign_id]["target_cpa_configured"],
    ):
        row["note"] = note
    if item := updated.get(key):
        row.update(outcome="updated", external_ref=item["resource_name"])
    elif key in already_set:
        criterion_id = existing["criterion_id"] if existing is not None else ""
        row.update(
            outcome="already_set",
            external_ref=(
                f"customers/{normalize_customer_id(customer_id)}/campaignCriteria/"
                f"{campaign_id}~{criterion_id}"
            ),
        )
    else:
        error = failed[key]
        row.update(
            outcome="failed",
            message=error.get("message"),
            error_code=error.get("error_code"),
        )
    return row


def _outcome_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item.get("campaign_id", "")), str(item.get("device", ""))


def _strategy_note(
    strategy: str,
    bid_modifier: float,
    *,
    target_cpa_configured: bool,
) -> str | None:
    ignores_nonzero = strategy in _IGNORED_NONZERO_STRATEGIES or (
        strategy == "MAXIMIZE_CONVERSIONS" and not target_cpa_configured
    )
    if bid_modifier != 0 and ignores_nonzero:
        return f"{strategy} does not use non-zero device bid adjustments for bidding."
    return None


def _modifier_text(value: float) -> str:
    return f"{rounded_bid_modifier(value):.2f}"


DEFINITION = RuntimeToolDefinition(
    name="google_ads_update_device_bid_modifiers",
    function=google_ads_update_device_bid_modifiers,
    description=(
        "Set device bid adjustments (desktop, mobile, tablet) on selected Google Ads "
        "campaigns. A bid modifier is a coefficient: 1.2 raises bids for that device by "
        "20%, 0.8 lowers them by 20%, 1.0 removes the adjustment, and 0 excludes the "
        "device entirely. Whether an adjustment has any effect depends on each campaign's "
        "bidding strategy, so first check campaign.bidding_strategy_type and its target "
        "fields with google_ads_run_report: Manual CPC, Enhanced CPC, and Maximize Clicks "
        "apply adjustments to bids; Target CPA, including Maximize Conversions with a "
        "configured target CPA, applies them to the CPA target. Target ROAS, Maximize "
        "Conversions without a target CPA, and Maximize Conversion Value ignore every "
        "device adjustment except 0. For campaigns on those strategies, only propose "
        "excluding a device (bid_modifier 0), and only when its performance justifies "
        "turning it off."
    ),
    provider="google_ads",
    label="Update Google Ads Device Bid Adjustments",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=60,
    output_model=GoogleAdsDeviceBidModifierOutput,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Updating Device Bid Adjustments",
        completed_label="Updated Device Bid Adjustments",
        failed_label="Couldn't Update Device Bid Adjustments",
        approval_title="Update Device Bid Adjustments",
        approval_prompt=(
            "The agent wants to change device bid adjustments on live campaigns. Review "
            "the campaigns and multipliers before changing how much these campaigns bid "
            "per device."
        ),
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
                key="adjustments",
                label="Device Bid Adjustments",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(
                        key="device",
                        label="Device",
                        options=("DESKTOP", "MOBILE", "TABLET"),
                        required=True,
                    ),
                    ToolFieldColumn(
                        key="bid_modifier",
                        label="Bid Modifier",
                        required=True,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
