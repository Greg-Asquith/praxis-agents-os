"""Google Ads low-level mutation-operation contracts."""

from uuid import uuid4

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.google_ads.operations.add_negative_keywords import add_negative_keywords
from integrations.google_ads.operations.create_negative_keyword_list import (
    create_negative_keyword_list,
)
from integrations.google_ads.operations.link_negative_keyword_list import (
    link_negative_keyword_list,
)
from integrations.google_ads.operations.remove_negative_keywords import (
    remove_negative_keywords,
)
from integrations.google_ads.operations.update_campaign_status import update_campaign_status
from integrations.google_ads.references import (
    GoogleAdsSharedSetReference,
)
from integrations.google_ads.tools.remove_negative_keywords import (
    _operation_detail as removal_operation_detail,
)
from tests.integrations.google_ads.support import (
    _CampaignSharedSetClient,
    _NegativeKeywordClient,
    _NegativeKeywordListClient,
    _OperationClient,
)


async def test_mutate_uses_partial_failure_and_surfaces_campaign_error() -> None:
    payload = {
        "results": [{"resourceName": "customers/333/campaigns/10"}],
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
    assert client.last_json["partialFailure"] is True
    assert client.last_login_customer_id == "111"
    assert result["resource_names"] == ["customers/333/campaigns/10"]
    assert result["campaign_errors"][0]["campaign_id"] == "20"
    assert result["campaign_errors"][0]["error_code"] == "CANNOT_MODIFY_REMOVED_CAMPAIGN"


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

    assert client.calls[0]["json"]["query"] == (
        "SELECT campaign_shared_set.campaign, campaign_shared_set.shared_set, "
        "campaign_shared_set.status "
        "FROM campaign_shared_set WHERE campaign_shared_set.shared_set = "
        "'customers/3333333333/sharedSets/50' AND campaign_shared_set.status = 'ENABLED'"
    )
    assert client.calls[1] == {
        "path": "customers/3333333333/campaignSharedSets:mutate",
        "operation": "link_negative_keyword_list",
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


async def test_unlink_negative_keyword_list_reports_not_found_and_composes_names() -> None:
    client = _CampaignSharedSetClient(
        search_payload={
            "results": [
                {
                    "campaignSharedSet": {
                        "campaign": "customers/333/campaigns/10",
                        "sharedSet": "customers/333/sharedSets/50",
                        "status": "ENABLED",
                    }
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/campaignSharedSets/10~50"},
            ]
        },
    )

    result = await link_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        campaign_ids=["10", "20"],
        action="UNLINK",
    )

    assert client.calls[1]["json"] == {
        "operations": [
            {"remove": "customers/333/campaignSharedSets/10~50"},
        ],
        "partialFailure": True,
    }
    assert result == {
        "resource_names": ["customers/333/campaignSharedSets/10~50"],
        "not_found": ["20"],
        "campaign_errors": [],
    }


async def test_link_negative_keyword_list_avoids_noop_mutate() -> None:
    client = _CampaignSharedSetClient(search_payload={"results": []}, mutate_payload={})

    result = await link_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        campaign_ids=["10"],
        action="UNLINK",
    )

    assert len(client.calls) == 1
    assert result == {
        "resource_names": [],
        "not_found": ["10"],
        "campaign_errors": [],
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


async def test_create_negative_keyword_list_skips_existing_and_maps_partial_failure() -> None:
    client = _NegativeKeywordListClient(
        search_payload=[
            {
                "results": [
                    {"sharedSet": {"id": "1", "name": "Existing List"}},
                ]
            }
        ],
        mutate_payload={
            "results": [{"resourceName": "customers/333/sharedSets/10"}, {}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "A list with this name is not allowed",
                                "errorCode": {"sharedSetError": "INVALID_NAME"},
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

    result = await create_negative_keyword_list(
        client,
        customer_id="333-333-3333",
        login_customer_id="111-111-1111",
        names=["existing list", "Created List", "Rejected List"],
    )

    assert client.calls[0] == {
        "path": "customers/3333333333/googleAds:searchStream",
        "operation": "list_negative_keyword_lists",
        "login_customer_id": "111-111-1111",
        "json": {
            "query": (
                "SELECT shared_set.id, shared_set.name FROM shared_set "
                "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' "
                "AND shared_set.status != 'REMOVED'"
            )
        },
    }
    assert client.calls[1]["path"] == "customers/3333333333/sharedSets:mutate"
    assert client.calls[1]["json"] == {
        "operations": [
            {"create": {"name": "Created List", "type": "NEGATIVE_KEYWORDS"}},
            {"create": {"name": "Rejected List", "type": "NEGATIVE_KEYWORDS"}},
        ],
        "partialFailure": True,
    }
    assert result == {
        "created_names": ["Created List"],
        "resource_names": ["customers/333/sharedSets/10"],
        "skipped_existing": ["existing list"],
        "list_errors": [
            {
                "name": "Rejected List",
                "message": "A list with this name is not allowed",
                "error_code": "INVALID_NAME",
            }
        ],
    }


async def test_create_negative_keyword_list_avoids_mutate_when_every_name_exists() -> None:
    client = _NegativeKeywordListClient(
        search_payload={
            "results": [
                {"sharedSet": {"id": "1", "name": "Existing List"}},
            ]
        },
        mutate_payload={"results": []},
    )

    result = await create_negative_keyword_list(
        client,
        customer_id="333",
        login_customer_id="111",
        names=["EXISTING LIST"],
    )

    assert len(client.calls) == 1
    assert result == {
        "created_names": [],
        "resource_names": [],
        "skipped_existing": ["EXISTING LIST"],
        "list_errors": [],
    }


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
        {"fieldPathElements": [{"fieldName": "operations", "index": "invalid"}]},
        {"fieldPathElements": [{"fieldName": "operations", "index": 9}]},
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


async def test_add_negative_keywords_preserves_message_only_partial_failure() -> None:
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={
            "results": [],
            "partialFailureError": {
                "code": 3,
                "message": "The request contained an unattributed failure",
            },
        },
    )

    result = await add_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[{"text": "Rejected phrase", "match_type": "PHRASE"}],
    )

    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "Rejected phrase",
            "match_type": "PHRASE",
            "message": "The request contained an unattributed failure",
            "error_code": "3",
        }
    ]


async def test_add_negative_keywords_groups_diagnostics_by_operation() -> None:
    location = {"fieldPathElements": [{"fieldName": "operations", "index": 0}]}
    client = _NegativeKeywordClient(
        search_payload={"results": []},
        mutate_payload={
            "results": [{}],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": location,
                            },
                            {
                                "message": "Remove punctuation",
                                "errorCode": {"requestError": "INVALID_INPUT"},
                                "location": location,
                            },
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
        keywords=[{"text": "Rejected phrase", "match_type": "PHRASE"}],
    )

    assert len(result["keyword_errors"]) == 1
    assert result["keyword_errors"][0]["message"] == (
        "Keyword is not permitted | Remove punctuation"
    )
    assert result["keyword_errors"][0]["error_code"] == ("INVALID_KEYWORD_TEXT | INVALID_INPUT")


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


async def test_remove_negative_keywords_rejects_any_expansion_above_audit_limit() -> None:
    search_rows = [
        {
            "sharedCriterion": {
                "criterionId": str(index * 3 + variant),
                "keyword": {"text": f"term {index}", "matchType": match_type},
            }
        }
        for index in range(167)
        for variant, match_type in enumerate(("EXACT", "PHRASE", "BROAD"), start=1)
    ]
    client = _NegativeKeywordClient(
        search_payload={"results": search_rows},
        mutate_payload={"results": []},
    )

    with pytest.raises(IntegrationValidationError, match="more than 500"):
        await remove_negative_keywords(
            client,
            customer_id="333",
            login_customer_id="111",
            shared_set_id="50",
            keywords=[{"text": f"term {index}", "match_type": "ANY"} for index in range(167)],
        )

    assert len(client.calls) == 1


async def test_remove_negative_keywords_maps_partial_failures_to_resolved_rows() -> None:
    client = _NegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "sharedCriterion": {
                        "criterionId": "1",
                        "keyword": {"text": "accepted", "matchType": "EXACT"},
                    }
                },
                {
                    "sharedCriterion": {
                        "criterionId": "2",
                        "keyword": {"text": "rejected", "matchType": "PHRASE"},
                    }
                },
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/sharedCriteria/50~1"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Criterion cannot be removed",
                                "errorCode": {"criterionError": "CANNOT_REMOVE_CRITERION"},
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

    result = await remove_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        shared_set_id="50",
        keywords=[
            {"text": "accepted", "match_type": "EXACT"},
            {"text": "rejected", "match_type": "PHRASE"},
        ],
    )

    assert result["resource_names"] == ["customers/333/sharedCriteria/50~1"]
    assert result["keyword_errors"] == [
        {
            "scope": "keyword",
            "text": "rejected",
            "match_type": "PHRASE",
            "message": "Criterion cannot be removed",
            "error_code": "CANNOT_REMOVE_CRITERION",
        }
    ]


def test_remove_negative_keyword_audit_detail_retains_removed_resource_names() -> None:
    reference = GoogleAdsSharedSetReference(
        integration_resource_id=uuid4(),
        external_id="50",
        label="Brand Protection",
    )

    detail = removal_operation_detail(
        reference,
        {
            "removed": [
                {
                    "text": "brand term",
                    "match_type": "EXACT",
                    "resource_name": "customers/333/sharedCriteria/50~1",
                }
            ],
            "not_found": [{"text": "missing", "match_type": "ANY"}],
            "keyword_errors": [],
        },
    )

    assert detail.changes[0].action == "remove"
    assert detail.changes[0].external_ref == "customers/333/sharedCriteria/50~1"
    assert detail.counts.model_dump() == {"applied": 1, "skipped": 1, "failed": 0}
