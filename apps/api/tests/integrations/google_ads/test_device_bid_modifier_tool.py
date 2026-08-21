"""Google Ads device bid modifier tool contracts and audit evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.update_device_bid_modifiers import (
    update_device_bid_modifiers,
)
from integrations.google_ads.references import GoogleAdsCampaignReference
from integrations.google_ads.tools.schemas import (
    GoogleAdsDeviceAdjustment,
    GoogleAdsDeviceBidModifierOutput,
)
from integrations.google_ads.tools.update_device_bid_modifiers import (
    DEFINITION,
    _normalize_adjustments,
    _pending_operation_detail,
    _strategy_note,
    google_ads_update_device_bid_modifiers,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry


def _entry(
    customer_id: str = "333",
    *,
    write_allowed: bool = True,
) -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id=customer_id,
        display_name="Ads account",
        connection_id=uuid4(),
        connection_label="Agency",
        connection_status="active",
        write_allowed=write_allowed,
        permissions_metadata={"login_customer_id": "111"},
    )


def _campaign(entry: ResolvedContextEntry, campaign_id: str) -> GoogleAdsCampaignReference:
    return GoogleAdsCampaignReference(
        customer_id=entry.external_id,
        campaign_id=campaign_id,
        label=f"Campaign {campaign_id}",
    )


def test_device_bid_modifier_definition_locks_strategy_guidance_and_presentation() -> None:
    assert DEFINITION.description == (
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
    )
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    fields = {field.key: field for field in DEFINITION.presentation.arg_fields}
    assert fields["campaign_ids"].format == "entity_list"
    assert fields["adjustments"].format == "records"
    assert fields["adjustments"].min_rows == 1
    assert fields["adjustments"].columns[0].options == (
        "DESKTOP",
        "MOBILE",
        "TABLET",
    )


def test_device_bid_modifier_normalization_matches_approval_and_result_precision() -> None:
    normalized = _normalize_adjustments(
        [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=1.234)]
    )

    assert normalized[0].bid_modifier == 1.23
    detail = _pending_operation_detail(_entry(), [_campaign(_entry(), "10")], normalized)
    assert detail.intent_groups[0].fields["bid_modifier"] == "1.23"


@pytest.mark.parametrize(
    ("strategy", "target_cpa_configured", "expects_note"),
    [
        ("MAXIMIZE_CONVERSIONS", False, True),
        ("MAXIMIZE_CONVERSIONS", True, False),
        ("TARGET_CPA", False, False),
        ("TARGET_ROAS", False, True),
    ],
)
def test_device_bid_modifier_strategy_note_distinguishes_target_cpa(
    strategy: str,
    target_cpa_configured: bool,
    expects_note: bool,
) -> None:
    note = _strategy_note(
        strategy,
        0.7,
        target_cpa_configured=target_cpa_configured,
    )

    assert (note is not None) is expects_note


@pytest.mark.parametrize("value", [0.05, 11.0])
async def test_device_bid_modifier_tool_rejects_invalid_modifiers_before_targeting(
    monkeypatch,
    value: float,
) -> None:
    targeting = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.run_context_targets",
        targeting,
    )

    with pytest.raises(ModelRetry, match=r"must be 0 or between 0\.1 and 10\.0"):
        await google_ads_update_device_bid_modifiers(
            None,  # type: ignore[arg-type]
            [_campaign(_entry(), "10")],
            [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=value)],
        )

    targeting.assert_not_awaited()


async def test_device_bid_modifier_tool_rejects_empty_campaigns_and_duplicate_devices(
    monkeypatch,
) -> None:
    targeting = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.run_context_targets",
        targeting,
    )
    adjustment = GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7)

    with pytest.raises(ModelRetry, match="at least one Google Ads campaign"):
        await google_ads_update_device_bid_modifiers(None, [], [adjustment])  # type: ignore[arg-type]
    with pytest.raises(ModelRetry, match="Each device can appear only once"):
        await google_ads_update_device_bid_modifiers(
            None,  # type: ignore[arg-type]
            [_campaign(_entry(), "10")],
            [adjustment, adjustment],
        )

    targeting.assert_not_awaited()


def test_device_bid_modifier_pending_detail_groups_each_device_and_campaign() -> None:
    entry = _entry()
    detail = _pending_operation_detail(
        entry,
        [_campaign(entry, "10"), _campaign(entry, "20")],
        [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7)],
    )

    [group] = detail.intent_groups
    assert group.key == "campaigns:update-device-bid-modifier:mobile"
    assert group.fields == {"device": "MOBILE", "bid_modifier": "0.70"}
    assert [item.fields for item in group.items] == [
        {
            "campaign_id": "10",
            "device": "MOBILE",
            "bid_modifier": "0.70",
            "campaign_name": "Campaign 10",
        },
        {
            "campaign_id": "20",
            "device": "MOBILE",
            "bid_modifier": "0.70",
            "campaign_name": "Campaign 20",
        },
    ]


async def test_device_bid_modifier_tool_reports_previous_values_skips_and_strategy_notes(
    monkeypatch,
) -> None:
    entry = _entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name=DEFINITION.name,
    )
    states = {
        "10": {
            "bidding_strategy_type": "MANUAL_CPC",
            "target_cpa_configured": False,
            "devices": {
                "MOBILE": {"criterion_id": "30001", "bid_modifier": 0.7},
            },
        },
        "20": {
            "bidding_strategy_type": "TARGET_ROAS",
            "target_cpa_configured": False,
            "devices": {
                "MOBILE": {"criterion_id": "30001", "bid_modifier": 1.0},
            },
        },
    }

    class Client:
        async def post(self, _path: str, **_kwargs):
            return {
                "results": [
                    {"resourceName": "customers/333/campaignCriteria/10~30002"},
                    {"resourceName": "customers/333/campaignCriteria/20~30001"},
                    {},
                ],
                "partialFailureError": {
                    "details": [
                        {
                            "errors": [
                                {
                                    "message": "Device criterion rejected",
                                    "errorCode": {"criterionError": "INVALID_DEVICE"},
                                    "location": {
                                        "fieldPathElements": [
                                            {"fieldName": "operations", "index": 2}
                                        ]
                                    },
                                }
                            ]
                        }
                    ]
                },
            }

    provider_client = Client()
    verifier = AsyncMock(return_value=states)
    audit_calls: list[dict] = []
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        audit_calls.append(kwargs)
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.verify_campaigns_for_device_bidding",
        verifier,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.update_device_bid_modifiers",
        update_device_bid_modifiers,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_update_device_bid_modifiers(
        ctx,
        [_campaign(entry, "10"), _campaign(entry, "20")],
        [
            GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7),
            GoogleAdsDeviceAdjustment(device="TABLET", bid_modifier=0),
        ],
    )

    [account] = result["results"]
    assert account["status"] == "success", repr(account)
    GoogleAdsDeviceBidModifierOutput.model_validate(result)
    campaigns = {item["campaign_id"]: item for item in account["data"]["campaigns"]}
    campaign_10 = {item["device"]: item for item in campaigns["10"]["devices"]}
    campaign_20 = {item["device"]: item for item in campaigns["20"]["devices"]}
    assert campaign_10["MOBILE"] == {
        "device": "MOBILE",
        "requested_bid_modifier": 0.7,
        "previous_bid_modifier": 0.7,
        "outcome": "already_set",
        "external_ref": "customers/333/campaignCriteria/10~30001",
    }
    assert campaigns["10"]["target_cpa_configured"] is False
    assert campaign_20["MOBILE"]["previous_bid_modifier"] == 1.0
    assert campaign_20["MOBILE"]["outcome"] == "updated"
    assert campaign_20["MOBILE"]["note"] == (
        "TARGET_ROAS does not use non-zero device bid adjustments for bidding."
    )
    assert "previous_bid_modifier" not in campaign_20["TABLET"]
    assert "note" not in campaign_20["TABLET"]
    assert campaign_20["TABLET"]["outcome"] == "failed"
    assert campaign_20["TABLET"]["error_code"] == "INVALID_DEVICE"
    assert len(audit_calls) == 1
    terminal_detail = audit_outcomes[0].operation_detail
    assert terminal_detail.intent_counts.model_dump() == {
        "applied": 2,
        "skipped": 1,
        "failed": 1,
        "unverified": 0,
    }


async def test_device_bid_modifier_tool_fails_closed_before_mutation(monkeypatch) -> None:
    entry = _entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name=DEFINITION.name,
    )
    mutation = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.google_ads_client",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.verify_campaigns_for_device_bidding",
        AsyncMock(side_effect=ModelRetry("A selected Google Ads campaign is unavailable.")),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.update_device_bid_modifiers",
        mutation,
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_update_device_bid_modifiers(
        ctx,
        [_campaign(entry, "10")],
        [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7)],
    )

    assert result["results"][0]["status"] == "error"
    assert result["results"][0]["error_code"] == "ModelRetry"
    mutation.assert_not_awaited()


async def test_device_bid_modifier_tool_rejects_cross_account_references(
    monkeypatch,
) -> None:
    entry = _entry("333")
    other_entry = _entry("444")
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name=DEFINITION.name,
    )
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.google_ads_client",
        provider_client,
    )

    with pytest.raises(ModelRetry, match="no longer in the active integration context"):
        await google_ads_update_device_bid_modifiers(
            ctx,
            [_campaign(other_entry, "10")],
            [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7)],
        )

    provider_client.assert_not_awaited()


async def test_device_bid_modifier_write_denial_is_audited_before_provider_call(
    monkeypatch,
) -> None:
    entry = _entry(write_allowed=False)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="call-denied",
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    result = await google_ads_update_device_bid_modifiers(
        ctx,
        [_campaign(entry, "10")],
        [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7)],
    )

    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["status"].value == "failure"
    assert audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_device_bid_modifier_durable_audit_failure_stops_provider_call(
    monkeypatch,
) -> None:
    entry = _entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name=DEFINITION.name,
        tool_call_id="call-audit-failure",
    )
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.update_device_bid_modifiers.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(side_effect=RuntimeError("pending audit unavailable")),
    )

    result = await google_ads_update_device_bid_modifiers(
        ctx,
        [_campaign(entry, "10")],
        [GoogleAdsDeviceAdjustment(device="MOBILE", bid_modifier=0.7)],
    )

    assert result["results"][0]["status"] == "error"
    assert "pending audit unavailable" in result["results"][0]["error_message"]
    provider_client.assert_not_awaited()
