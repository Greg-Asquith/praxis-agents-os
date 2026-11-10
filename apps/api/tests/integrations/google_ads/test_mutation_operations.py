# apps/api/tests/integrations/google_ads/test_mutation_operations.py

"""Google Ads low-level mutation-operation contracts."""

from integrations.google_ads.operations.update_device_bid_modifiers import (
    update_device_bid_modifiers,
)
from tests.integrations.google_ads.support import (
    _OperationClient,
)


async def test_update_device_bid_modifiers_mixes_create_update_and_skip() -> None:
    client = _OperationClient(
        {
            "results": [
                {"resourceName": "customers/333/campaignCriteria/10~30000"},
                {"resourceName": "customers/333/campaignCriteria/10~30001"},
                {"resourceName": "customers/333/campaignCriteria/20~30002"},
            ]
        }
    )
    result = await update_device_bid_modifiers(
        client,
        customer_id="333",
        login_customer_id="111",
        adjustments=[
            ("10", "DESKTOP", 1.0),
            ("10", "MOBILE", 0.0),
            ("20", "TABLET", 1.2),
            ("20", "MOBILE", 0.8),
        ],
        existing_state={
            "10": {
                "bidding_strategy_type": "MANUAL_CPC",
                "devices": {
                    "MOBILE": {"criterion_id": "30001", "bid_modifier": 0.7},
                },
            },
            "20": {
                "bidding_strategy_type": "TARGET_ROAS",
                "devices": {
                    "MOBILE": {"criterion_id": "30001", "bid_modifier": 0.8},
                    "TABLET": {"criterion_id": "30002", "bid_modifier": 1.0},
                },
            },
        },
    )

    assert client.last_json == {
        "operations": [
            {
                "create": {
                    "campaign": "customers/333/campaigns/10",
                    "device": {"type": "DESKTOP"},
                    "bidModifier": 1.0,
                }
            },
            {
                "update": {
                    "resourceName": "customers/333/campaignCriteria/10~30001",
                    "bidModifier": 0.0,
                },
                "updateMask": "bidModifier",
            },
            {
                "update": {
                    "resourceName": "customers/333/campaignCriteria/20~30002",
                    "bidModifier": 1.2,
                },
                "updateMask": "bidModifier",
            },
        ],
        "partialFailure": True,
    }
    assert result.result() == {
        "updated": [
            {
                "campaign_id": "10",
                "device": "DESKTOP",
                "bid_modifier": "1.00",
                "resource_name": "customers/333/campaignCriteria/10~30000",
            },
            {
                "campaign_id": "10",
                "device": "MOBILE",
                "bid_modifier": "0.00",
                "resource_name": "customers/333/campaignCriteria/10~30001",
            },
            {
                "campaign_id": "20",
                "device": "TABLET",
                "bid_modifier": "1.20",
                "resource_name": "customers/333/campaignCriteria/20~30002",
            },
        ],
        "already_set": [{"campaign_id": "20", "device": "MOBILE", "bid_modifier": "0.80"}],
        "device_errors": [],
        "resource_names": [
            "customers/333/campaignCriteria/10~30000",
            "customers/333/campaignCriteria/10~30001",
            "customers/333/campaignCriteria/20~30002",
        ],
    }
    skipped_parent = result.parents[3]
    assert result.skipped_external_ref(skipped_parent) == (
        "customers/333/campaignCriteria/20~30001"
    )


async def test_update_device_bid_modifiers_uses_two_decimal_skip_comparison() -> None:
    client = _OperationClient({"results": []})
    result = await update_device_bid_modifiers(
        client,
        customer_id="333",
        login_customer_id="111",
        adjustments=[("10", "MOBILE", 1.2)],
        existing_state={
            "10": {
                "bidding_strategy_type": "MANUAL_CPC",
                "devices": {"MOBILE": {"criterion_id": "30001", "bid_modifier": 1.20}},
            }
        },
    )

    assert result["already_set"] == [
        {"campaign_id": "10", "device": "MOBILE", "bid_modifier": "1.20"}
    ]
    assert client.last_json is None
