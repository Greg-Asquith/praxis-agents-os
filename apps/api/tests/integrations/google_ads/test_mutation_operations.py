"""Google Ads low-level mutation-operation contracts."""

import pytest

from integrations.google_ads.operations.add_negative_keywords import add_negative_keywords
from integrations.google_ads.operations.create_negative_keyword_list import (
    create_negative_keyword_list,
)
from integrations.google_ads.operations.link_negative_keyword_list import (
    link_negative_keyword_list,
)
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
)
from integrations.google_ads.operations.remove_negative_keywords import (
    remove_negative_keywords,
)
from integrations.google_ads.operations.update_campaign_status import update_campaign_status
from integrations.google_ads.operations.update_device_bid_modifiers import (
    update_device_bid_modifiers,
)
from services.integrations.http import IntegrationRequestPolicy
from tests.integrations.google_ads.support import (
    _CampaignSharedSetClient,
    _NegativeKeywordClient,
    _NegativeKeywordListClient,
    _OperationClient,
)


async def test_mutate_uses_partial_failure_and_surfaces_campaign_error() -> None:
    payload = {
        "results": [{"resourceName": "customers/333/campaigns/10"}, {}],
        "partialFailureError": {
            "details": [
                {
                    "errors": [
                        {
                            "message": "Campaign is removed",
                            "errorCode": {"campaignError": "CANNOT_MODIFY_REMOVED_CAMPAIGN"},
                            "location": {
                                "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                            },
                        }
                    ]
                }
            ]
        },
    }
    client = _OperationClient(payload)
    result = await update_campaign_status(
        client,
        customer_id="333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        status="PAUSED",
    )
    assert type(result) is GoogleAdsMutationLedger
    assert client.last_json["partialFailure"] is True
    assert client.last_login_customer_id == "111"
    assert result["resource_names"] == ["customers/333/campaigns/10"]
    assert result["campaign_errors"][0]["campaign_id"] == "20"
    assert result["campaign_errors"][0]["error_code"] == "CANNOT_MODIFY_REMOVED_CAMPAIGN"


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


async def test_update_device_bid_modifiers_fails_closed_for_unattributed_errors() -> None:
    client = _OperationClient(
        {
            "results": [
                {"resourceName": "customers/333/campaignCriteria/10~30000"},
                {"resourceName": "customers/333/campaignCriteria/10~30001"},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Unattributed device failure",
                                "errorCode": {"criterionError": "UNKNOWN_DEVICE_FAILURE"},
                            }
                        ]
                    }
                ]
            },
        }
    )

    result = await update_device_bid_modifiers(
        client,
        customer_id="333",
        login_customer_id="111",
        adjustments=[("10", "DESKTOP", 1.0), ("10", "MOBILE", 0.7)],
        existing_state={
            "10": {
                "bidding_strategy_type": "MANUAL_CPC",
                "target_cpa_configured": False,
                "devices": {},
            }
        },
    )

    assert {item["error_code"] for item in result["device_errors"]} == {"UNKNOWN_DEVICE_FAILURE"}
    assert all(effect.outcome == "unverified" for effect in result.effects)


@pytest.mark.parametrize(
    "results",
    [
        [{"resourceName": "customers/333/campaigns/10"}],
        [
            {"resourceName": "customers/333/campaigns/10"},
            {"resourceName": "customers/333/campaigns/20"},
            {"resourceName": "customers/333/campaigns/30"},
        ],
        [{"resourceName": "customers/333/campaigns/10"}, "malformed"],
    ],
    ids=["short", "long", "malformed"],
)
async def test_campaign_status_fails_closed_for_invalid_result_evidence(
    results: list[object],
) -> None:
    result = await update_campaign_status(
        _OperationClient({"results": results}),
        customer_id="333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        status="PAUSED",
    )

    assert result["resource_names"] == []
    assert [error["campaign_id"] for error in result["campaign_errors"]] == ["10", "20"]
    assert {error["error_code"] for error in result["campaign_errors"]} == {"UNACCOUNTED_OPERATION"}


async def test_link_negative_keyword_list_skips_existing_and_maps_failures() -> None:
    client = _CampaignSharedSetClient(
        search_payload={
            "results": [
                {
                    "campaignSharedSet": {
                        "campaign": "customers/3333333333/campaigns/10",
                        "sharedSet": "customers/3333333333/sharedSets/50",
                        "status": "ENABLED",
                    }
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/3333333333/campaignSharedSets/20~50"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Campaign is removed",
                                "errorCode": {"campaignSharedSetError": "CAMPAIGN_REMOVED"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await link_negative_keyword_list(
        client,
        customer_id="333-333-3333",
        login_customer_id="111-111-1111",
        shared_set_id="50",
        campaign_ids=["10", "20", "30"],
        action="LINK",
    )
    assert type(result) is GoogleAdsMutationLedger

    assert client.calls[0]["json"]["query"] == (
        "SELECT campaign_shared_set.campaign, campaign_shared_set.shared_set, "
        "campaign_shared_set.status "
        "FROM campaign_shared_set WHERE campaign_shared_set.shared_set = "
        "'customers/3333333333/sharedSets/50' AND campaign_shared_set.status = 'ENABLED'"
    )
    assert client.calls[1] == {
        "path": "customers/3333333333/campaignSharedSets:mutate",
        "operation": "link_negative_keyword_list",
        "policy": IntegrationRequestPolicy.MUTATION,
        "login_customer_id": "111-111-1111",
        "json": {
            "operations": [
                {
                    "create": {
                        "campaign": "customers/3333333333/campaigns/20",
                        "sharedSet": "customers/3333333333/sharedSets/50",
                    }
                },
                {
                    "create": {
                        "campaign": "customers/3333333333/campaigns/30",
                        "sharedSet": "customers/3333333333/sharedSets/50",
                    }
                },
            ],
            "partialFailure": True,
        },
    }
    assert result == {
        "resource_names": ["customers/3333333333/campaignSharedSets/20~50"],
        "skipped_existing": ["10"],
        "campaign_errors": [
            {
                "campaign_id": "30",
                "message": "Campaign is removed",
                "error_code": "CAMPAIGN_REMOVED",
            }
        ],
    }


async def test_link_negative_keyword_list_does_not_treat_removed_link_as_existing() -> None:
    client = _CampaignSharedSetClient(
        search_payload={
            "results": [
                {
                    "campaignSharedSet": {
                        "campaign": "customers/333/campaigns/10",
                        "sharedSet": "customers/333/sharedSets/50",
                        "status": "REMOVED",
                    }
                }
            ]
        },
        mutate_payload={"results": [{"resourceName": "customers/333/campaignSharedSets/10~50"}]},
    )

    result = await link_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        campaign_ids=["10"],
        action="LINK",
    )

    assert len(client.calls) == 2
    assert result == {
        "resource_names": ["customers/333/campaignSharedSets/10~50"],
        "skipped_existing": [],
        "campaign_errors": [],
    }


@pytest.mark.parametrize(
    ("results", "expected_resource_names"),
    [
        (
            [
                {"resourceName": "customers/333/sharedSets/10"},
                {"resourceName": "customers/333/sharedSets/20"},
            ],
            ["customers/333/sharedSets/10", "customers/333/sharedSets/20"],
        ),
        ([{"resourceName": "customers/333/sharedSets/10"}], []),
        (
            [
                {"resourceName": "customers/333/sharedSets/10"},
                {"resourceName": "customers/333/sharedSets/20"},
                {"resourceName": "customers/333/sharedSets/30"},
            ],
            [],
        ),
    ],
    ids=["exact", "short", "long"],
)
async def test_create_negative_keyword_list_accounts_for_every_result_slot(
    results: list[object],
    expected_resource_names: list[str],
) -> None:
    client = _NegativeKeywordListClient(
        search_payload={"results": []},
        mutate_payload={"results": results},
    )

    result = await create_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        names=["First List", "Second List"],
    )

    assert result["resource_names"] == expected_resource_names
    if expected_resource_names:
        assert result["created_names"] == ["First List", "Second List"]
        assert result["list_errors"] == []
    else:
        assert result["created_names"] == []
        assert [error["name"] for error in result["list_errors"]] == [
            "First List",
            "Second List",
        ]
        assert {error["error_code"] for error in result["list_errors"]} == {"UNACCOUNTED_OPERATION"}


async def test_add_negative_keywords_skips_pairs_and_maps_partial_failures() -> None:
    client = _NegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "sharedCriterion": {
                        "criterionId": "1",
                        "keyword": {"text": "Existing Term", "matchType": "EXACT"},
                    }
                }
            ]
        },
        mutate_payload={
            "results": [{"resourceName": "customers/333/sharedCriteria/10~20"}, {}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 1}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await add_negative_keywords(
        client,
        customer_id="333-333-3333",
        login_customer_id="111-111-1111",
        shared_set_id="50",
        keywords=[
            {"text": "existing term", "match_type": "EXACT"},
            {"text": "Created phrase", "match_type": "PHRASE"},
            {"text": "Rejected broad", "match_type": "BROAD"},
        ],
    )
    assert type(result) is GoogleAdsMutationLedger

    assert (
        "shared_criterion.shared_set = 'customers/3333333333/sharedSets/50'"
        in client.calls[0]["json"]["query"]
    )
    assert client.calls[1]["path"] == "customers/3333333333/sharedCriteria:mutate"
    assert client.calls[1]["json"] == {
        "operations": [
            {
                "create": {
                    "sharedSet": "customers/3333333333/sharedSets/50",
                    "keyword": {"text": "Created phrase", "matchType": "PHRASE"},
                }
            },
            {
                "create": {
                    "sharedSet": "customers/3333333333/sharedSets/50",
                    "keyword": {"text": "Rejected broad", "matchType": "BROAD"},
                }
            },
        ],
        "partialFailure": True,
    }
    assert result == {
        "added": [
            {
                "text": "Created phrase",
                "match_type": "PHRASE",
                "resource_name": "customers/333/sharedCriteria/10~20",
            }
        ],
        "skipped_existing": [{"text": "existing term", "match_type": "EXACT"}],
        "keyword_errors": [
            {
                "scope": "keyword",
                "text": "Rejected broad",
                "match_type": "BROAD",
                "message": "Keyword is not permitted",
                "error_code": "INVALID_KEYWORD_TEXT",
            }
        ],
    }


@pytest.mark.parametrize(
    "location",
    [
        {},
        {"fieldPathElements": [{"fieldName": "operations"}]},
    ],
)
async def test_add_negative_keywords_fails_closed_for_unattributed_partial_failures(
    location: dict[str, object],
) -> None:
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={
            "results": [{"resourceName": "customers/333/sharedCriteria/50~1"}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "The account rejected part of the request",
                                "errorCode": {"requestError": "INVALID_INPUT"},
                                "location": location,
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Created phrase", "match_type": "PHRASE"}],
    )

    assert result["added"] == []
    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "Created phrase",
            "match_type": "PHRASE",
            "message": "The account rejected part of the request",
            "error_code": "INVALID_INPUT",
        }
    ]


async def test_add_negative_keywords_fails_closed_for_unaccounted_results() -> None:
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={"results": []},
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Unaccounted", "match_type": "EXACT"}],
    )

    assert result["added"] == []
    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "Unaccounted",
            "match_type": "EXACT",
            "message": "Google Ads did not account for this submitted operation",
            "error_code": "UNACCOUNTED_OPERATION",
        }
    ]


async def test_remove_negative_keywords_resolves_precise_and_any_rows() -> None:
    client = _NegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "sharedCriterion": {
                        "criterionId": "1",
                        "keyword": {"text": "Brand Term", "matchType": "EXACT"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "2",
                        "keyword": {"text": "Generic Term", "matchType": "PHRASE"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "3",
                        "keyword": {"text": "generic term", "matchType": "BROAD"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "4",
                        "keyword": {"text": "Keep Me", "matchType": "BROAD"},
                    }
                },
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/3333333333/sharedCriteria/50~1"},
                {"resourceName": "customers/3333333333/sharedCriteria/50~2"},
                {"resourceName": "customers/3333333333/sharedCriteria/50~3"},
            ]
        },
    )

    result = await remove_negative_keywords(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[
            {"text": "brand term", "match_type": "EXACT"},
            {"text": "GENERIC TERM", "match_type": "ANY"},
            {"text": "missing", "match_type": "PHRASE"},
        ],
    )
    assert type(result) is GoogleAdsMutationLedger

    assert "shared_criterion.criterion_id" in client.calls[0]["json"]["query"]
    assert client.calls[1]["json"] == {
        "operations": [
            {"remove": "customers/3333333333/sharedCriteria/50~1"},
            {"remove": "customers/3333333333/sharedCriteria/50~2"},
            {"remove": "customers/3333333333/sharedCriteria/50~3"},
        ],
        "partialFailure": True,
    }
    assert result["resource_names"] == [
        "customers/3333333333/sharedCriteria/50~1",
        "customers/3333333333/sharedCriteria/50~2",
        "customers/3333333333/sharedCriteria/50~3",
    ]
    assert [(item["text"], item["match_type"]) for item in result["removed"]] == [
        ("Brand Term", "EXACT"),
        ("Generic Term", "PHRASE"),
        ("generic term", "BROAD"),
    ]
    assert result["not_found"] == [{"text": "missing", "match_type": "PHRASE"}]
    assert result["keyword_errors"] == []


async def test_remove_negative_keywords_never_mutates_not_found_rows() -> None:
    client = _NegativeKeywordClient(search_payload={"results": []}, mutate_payload={})

    result = await remove_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "absent", "match_type": "ANY"}],
    )

    assert len(client.calls) == 1
    assert result == {
        "removed": [],
        "resource_names": [],
        "not_found": [{"text": "absent", "match_type": "ANY"}],
        "keyword_errors": [],
    }
