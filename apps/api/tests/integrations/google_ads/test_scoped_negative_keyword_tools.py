"""Google Ads campaign and ad-group negative-keyword tool contracts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.google_ads.operations.ad_group_negative_keywords import (
    add_ad_group_negative_keywords,
    remove_ad_group_negative_keywords,
)
from integrations.google_ads.operations.campaign_negative_keywords import (
    add_campaign_negative_keywords,
    remove_campaign_negative_keywords,
)
from integrations.google_ads.operations.mutation_outcomes import (
    AD_GROUP_KEYWORD_MUTATION_SPEC,
    CAMPAIGN_KEYWORD_MUTATION_SPEC,
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_keyword_mutation_ledger,
    build_mutation_ledger,
)
from integrations.google_ads.tools.add_ad_group_negative_keywords import (
    google_ads_add_ad_group_negative_keywords,
)
from integrations.google_ads.tools.add_campaign_negative_keywords import (
    google_ads_add_campaign_negative_keywords,
)
from integrations.google_ads.tools.remove_ad_group_negative_keywords import (
    google_ads_remove_ad_group_negative_keywords,
)
from integrations.google_ads.tools.remove_campaign_negative_keywords import (
    google_ads_remove_campaign_negative_keywords,
)
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from integrations.google_ads.tools.utils.ad_group_negative_keywords import (
    AD_GROUP_NEGATIVE_KEYWORD_TOOL_SPEC,
)
from integrations.google_ads.tools.utils.campaign_negative_keywords import (
    CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS,
)
from integrations.google_ads.tools.utils.mutation_evidence import terminal_operation_detail
from integrations.google_ads.tools.utils.negative_keyword_tools import (
    entity_result,
    pending_operation_detail,
)
from services.audit_events import AuditStatus
from services.audit_events.integration_operation_detail import (
    MAX_INTEGRATION_OPERATION_DETAIL_BYTES,
)
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import (
    _ad_group_reference,
    _AdGroupNegativeKeywordClient,
    _campaign_reference,
    _CampaignNegativeKeywordClient,
    _writable_google_ads_entry,
    mutation_ledger,
)


@pytest.mark.parametrize(
    (
        "entity_kind",
        "add_operation",
        "remove_operation",
        "id_argument",
        "id_key",
        "errors_key",
        "response_entity_key",
        "response_criterion_key",
        "criterion_path",
    ),
    [
        (
            "campaign",
            add_campaign_negative_keywords,
            remove_campaign_negative_keywords,
            "campaign_ids",
            "campaign_id",
            "campaign_errors",
            "campaign",
            "campaignCriterion",
            "campaignCriteria",
        ),
        (
            "ad_group",
            add_ad_group_negative_keywords,
            remove_ad_group_negative_keywords,
            "ad_group_ids",
            "ad_group_id",
            "ad_group_errors",
            "adGroup",
            "adGroupCriterion",
            "adGroupCriteria",
        ),
    ],
)
async def test_scoped_negative_keyword_operation_parity_matrix(
    entity_kind,
    add_operation,
    remove_operation,
    id_argument,
    id_key,
    errors_key,
    response_entity_key,
    response_criterion_key,
    criterion_path,
) -> None:
    client_type = (
        _CampaignNegativeKeywordClient
        if entity_kind == "campaign"
        else _AdGroupNegativeKeywordClient
    )
    existing_resource = f"customers/333/{criterion_path}/20~1"
    add_client = client_type(
        search_payload={
            "results": [
                {
                    response_entity_key: {"id": "20"},
                    response_criterion_key: {
                        "resourceName": existing_resource,
                        "keyword": {"text": "existing", "matchType": "EXACT"},
                    },
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": f"customers/333/{criterion_path}/20~2"},
                {},
                {"resourceName": f"customers/333/{criterion_path}/10~3"},
            ],
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
    call_arguments = {
        "customer_id": "333-333-3333",
        "login_customer_id": "111",
        id_argument: ["20", "10", "20"],
        "keywords": [
            {"text": "existing", "match_type": "EXACT"},
            {"text": "phrase", "match_type": "PHRASE"},
        ],
    }

    added = await add_operation(add_client, **call_arguments)

    assert isinstance(added, GoogleAdsMutationLedger)
    assert added["skipped_existing"] == [{id_key: "20", "text": "existing", "match_type": "EXACT"}]
    assert [(row[id_key], row["text"]) for row in added["added"]] == [
        ("20", "phrase"),
        ("10", "phrase"),
    ]
    assert added[errors_key] == [
        {
            id_key: "10",
            "text": "existing",
            "match_type": "EXACT",
            "message": "Keyword is not permitted",
            "error_code": "INVALID_KEYWORD_TEXT",
        }
    ]
    assert add_client.calls[1]["json"]["partialFailure"] is True

    removal_client = client_type(
        search_payload={
            "results": [
                {
                    response_entity_key: {"id": "20"},
                    response_criterion_key: {
                        "resourceName": f"customers/333/{criterion_path}/20~{index}",
                        "keyword": {"text": "TERM", "matchType": match_type},
                    },
                }
                for index, match_type in enumerate(("EXACT", "BROAD"), start=1)
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": f"customers/333/{criterion_path}/20~1"},
                {"resourceName": f"customers/333/{criterion_path}/20~2"},
            ]
        },
    )
    removed = await remove_operation(
        removal_client,
        customer_id="333",
        login_customer_id="111",
        **{id_argument: ["20", "10"]},
        keywords=[{"text": "term", "match_type": "ANY"}],
    )

    assert isinstance(removed, GoogleAdsMutationLedger)
    assert [(row[id_key], row["match_type"]) for row in removed["removed"]] == [
        ("20", "EXACT"),
        ("20", "BROAD"),
    ]
    assert removed["not_found"] == [{id_key: "10", "text": "term", "match_type": "ANY"}]
    assert removed[errors_key] == []
    with pytest.raises(IntegrationValidationError, match="2,500"):
        await add_operation(
            add_client,
            customer_id="333",
            login_customer_id="111",
            **{id_argument: [str(index) for index in range(51)]},
            keywords=[{"text": str(index), "match_type": "EXACT"} for index in range(50)],
        )


async def test_add_campaign_negative_keywords_skips_per_campaign_and_maps_errors() -> None:
    client = _CampaignNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "campaign": {"id": "10"},
                    "campaignCriterion": {
                        "resourceName": "customers/333/campaignCriteria/10~1",
                        "keyword": {"text": "existing", "matchType": "EXACT"},
                    },
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/campaignCriteria/10~2"},
                {"resourceName": "customers/333/campaignCriteria/20~3"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 2}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    result = await add_campaign_negative_keywords(
        client,
        customer_id="333-333-3333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        keywords=[
            {"text": "existing", "match_type": "EXACT"},
            {"text": "phrase", "match_type": "PHRASE"},
        ],
    )

    assert "campaign_criterion.negative = TRUE" in client.calls[0]["json"]["query"]
    assert "campaign.id IN (10, 20)" in client.calls[0]["json"]["query"]
    assert client.calls[1]["path"] == "customers/3333333333/campaignCriteria:mutate"
    assert client.calls[1]["json"]["operations"] == [
        {
            "create": {
                "campaign": "customers/3333333333/campaigns/10",
                "negative": True,
                "keyword": {"text": "phrase", "matchType": "PHRASE"},
            }
        },
        {
            "create": {
                "campaign": "customers/3333333333/campaigns/20",
                "negative": True,
                "keyword": {"text": "existing", "matchType": "EXACT"},
            }
        },
        {
            "create": {
                "campaign": "customers/3333333333/campaigns/20",
                "negative": True,
                "keyword": {"text": "phrase", "matchType": "PHRASE"},
            }
        },
    ]
    assert client.calls[1]["json"]["partialFailure"] is True
    assert result["skipped_existing"] == [
        {"campaign_id": "10", "text": "existing", "match_type": "EXACT"}
    ]
    assert [(item["campaign_id"], item["match_type"]) for item in result["added"]] == [
        ("10", "PHRASE"),
        ("20", "EXACT"),
    ]
    assert result["campaign_errors"] == [
        {
            "campaign_id": "20",
            "text": "phrase",
            "match_type": "PHRASE",
            "message": "Keyword is not permitted",
            "error_code": "INVALID_KEYWORD_TEXT",
        }
    ]


async def test_remove_campaign_negative_keywords_resolves_each_campaign_and_any() -> None:
    rows = [
        ("10", "1", "term", "EXACT"),
        ("10", "2", "term", "BROAD"),
        ("20", "3", "Term", "PHRASE"),
    ]
    client = _CampaignNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "campaign": {"id": campaign_id},
                    "campaignCriterion": {
                        "resourceName": f"customers/333/campaignCriteria/{campaign_id}~{criterion_id}",
                        "keyword": {"text": text, "matchType": match_type},
                    },
                }
                for campaign_id, criterion_id, text, match_type in rows
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/campaignCriteria/10~1"},
                {},
                {"resourceName": "customers/333/campaignCriteria/20~3"},
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

    result = await remove_campaign_negative_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        campaign_ids=["10", "20"],
        keywords=[
            {"text": "TERM", "match_type": "ANY"},
            {"text": "missing", "match_type": "EXACT"},
        ],
    )

    assert client.calls[1]["json"] == {
        "operations": [
            {"remove": "customers/333/campaignCriteria/10~1"},
            {"remove": "customers/333/campaignCriteria/10~2"},
            {"remove": "customers/333/campaignCriteria/20~3"},
        ],
        "partialFailure": True,
    }
    assert [(item["campaign_id"], item["match_type"]) for item in result["removed"]] == [
        ("10", "EXACT"),
        ("20", "PHRASE"),
    ]
    assert result["not_found"] == [
        {"campaign_id": "10", "text": "missing", "match_type": "EXACT"},
        {"campaign_id": "20", "text": "missing", "match_type": "EXACT"},
    ]
    assert result["campaign_errors"][0]["campaign_id"] == "10"
    assert result["campaign_errors"][0]["match_type"] == "BROAD"


async def test_campaign_negative_keyword_fan_out_bound_accepts_2500_operations(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_add_campaign_negative_keywords",
    )
    client = AsyncMock()
    client.post.return_value = {
        "results": [{"campaign": {"id": str(index), "status": "ENABLED"}} for index in range(1, 51)]
    }
    provider_add = AsyncMock(
        return_value=mutation_ledger(
            {
                "added": [],
                "resource_names": [],
                "skipped_existing": [
                    {
                        "campaign_id": str(campaign_index),
                        "text": f"term {keyword_index}",
                        "match_type": "EXACT",
                    }
                    for campaign_index in range(1, 51)
                    for keyword_index in range(50)
                ],
                "campaign_errors": [],
            }
        )
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.add_campaign_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_add_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, str(index)) for index in range(1, 51)],
        [NegativeKeywordEntry(text=f"term {index}", match_type="EXACT") for index in range(50)],
    )

    assert result.return_value["results"][0]["status"] == "success"
    assert len(provider_add.await_args.kwargs["campaign_ids"]) == 50
    assert len(provider_add.await_args.kwargs["keywords"]) == 50
    assert "keyword_outcomes" not in result.return_value["results"][0]["data"]["campaigns"][0]
    public_campaigns = result.metadata["public_result"]["results"][0]["data"]["campaigns"]
    assert sum(len(campaign["keyword_outcomes"]) for campaign in public_campaigns) == 2_500


async def test_campaign_negative_keyword_fan_out_bound_rejects_3000_before_provider(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_remove_campaign_negative_keywords",
    )
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        provider_client,
    )

    result = await google_ads_remove_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, str(index)) for index in range(1, 7)],
        [
            NegativeKeywordRemovalEntry(text=f"term {index}", match_type="ANY")
            for index in range(500)
        ],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "2,500" in result.return_value["results"][0]["error_message"]
    provider_client.assert_not_awaited()


async def test_campaign_negative_keywords_fail_closed_when_campaign_is_missing(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_add_campaign_negative_keywords",
    )
    client = AsyncMock()
    client.post.return_value = {"results": []}
    provider_add = AsyncMock()

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.campaign_negative_keywords.add_campaign_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.run_audited_integration_operation",
        passthrough_audit,
    )

    result = await google_ads_add_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )

    assert result.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "campaign is unavailable" in result.return_value["results"][0]["error_message"]
    provider_add.assert_not_awaited()


async def test_campaign_negative_keyword_write_denial_is_audited_before_provider(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry(write_allowed=False)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_add_campaign_negative_keywords",
        tool_call_id="call-add-denied",
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    add_result = await google_ads_add_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )
    ctx.tool_name = "google_ads_remove_campaign_negative_keywords"
    remove_result = await google_ads_remove_campaign_negative_keywords(
        ctx,
        [_campaign_reference(entry, "10")],
        [NegativeKeywordRemovalEntry(text="term", match_type="EXACT")],
    )

    assert add_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    assert remove_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert [call.kwargs["operation"] for call in audit.await_args_list] == [
        "add_campaign_negative_keywords",
        "remove_campaign_negative_keywords",
    ]
    assert all(call.kwargs["status"] == AuditStatus.FAILURE for call in audit.await_args_list)


async def test_ad_group_negative_keyword_operations_skip_resolve_and_map_rows() -> None:
    add_client = _AdGroupNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "adGroup": {"id": "10"},
                    "adGroupCriterion": {
                        "resourceName": "customers/333/adGroupCriteria/10~1",
                        "keyword": {"text": "existing", "matchType": "EXACT"},
                    },
                }
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/adGroupCriteria/10~2"},
                {"resourceName": "customers/333/adGroupCriteria/20~3"},
                {},
            ],
            "partialFailureError": {
                "details": [
                    {
                        "errors": [
                            {
                                "message": "Keyword is not permitted",
                                "errorCode": {"criterionError": "INVALID_KEYWORD_TEXT"},
                                "location": {
                                    "fieldPathElements": [{"fieldName": "operations", "index": 2}]
                                },
                            }
                        ]
                    }
                ]
            },
        },
    )

    added = await add_ad_group_negative_keywords(
        add_client,
        customer_id="333-333-3333",
        login_customer_id="111",
        ad_group_ids=["10", "20"],
        keywords=[
            {"text": "existing", "match_type": "EXACT"},
            {"text": "phrase", "match_type": "PHRASE"},
        ],
    )

    assert "ad_group_criterion.negative = TRUE" in add_client.calls[0]["json"]["query"]
    assert "ad_group.id IN (10, 20)" in add_client.calls[0]["json"]["query"]
    assert add_client.calls[1]["path"] == "customers/3333333333/adGroupCriteria:mutate"
    assert add_client.calls[1]["json"]["operations"][0]["create"] == {
        "adGroup": "customers/3333333333/adGroups/10",
        "negative": True,
        "keyword": {"text": "phrase", "matchType": "PHRASE"},
    }
    assert added["skipped_existing"] == [
        {"ad_group_id": "10", "text": "existing", "match_type": "EXACT"}
    ]
    assert [(item["ad_group_id"], item["match_type"]) for item in added["added"]] == [
        ("10", "PHRASE"),
        ("20", "EXACT"),
    ]
    assert added["ad_group_errors"][0]["ad_group_id"] == "20"

    rows = [("10", "1", "term", "EXACT"), ("10", "2", "term", "BROAD")]
    remove_client = _AdGroupNegativeKeywordClient(
        search_payload={
            "results": [
                {
                    "adGroup": {"id": ad_group_id},
                    "adGroupCriterion": {
                        "resourceName": (
                            f"customers/333/adGroupCriteria/{ad_group_id}~{criterion_id}"
                        ),
                        "keyword": {"text": text, "matchType": match_type},
                    },
                }
                for ad_group_id, criterion_id, text, match_type in rows
            ]
        },
        mutate_payload={
            "results": [
                {"resourceName": "customers/333/adGroupCriteria/10~1"},
                {"resourceName": "customers/333/adGroupCriteria/10~2"},
            ]
        },
    )
    removed = await remove_ad_group_negative_keywords(
        remove_client,
        customer_id="333",
        login_customer_id="111",
        ad_group_ids=["10", "20"],
        keywords=[
            {"text": "TERM", "match_type": "ANY"},
            {"text": "missing", "match_type": "EXACT"},
        ],
    )
    assert remove_client.calls[1]["json"]["operations"] == [
        {"remove": "customers/333/adGroupCriteria/10~1"},
        {"remove": "customers/333/adGroupCriteria/10~2"},
    ]
    assert len(removed["removed"]) == 2
    assert removed["not_found"] == [
        {"ad_group_id": "10", "text": "missing", "match_type": "EXACT"},
        {"ad_group_id": "20", "text": "TERM", "match_type": "ANY"},
        {"ad_group_id": "20", "text": "missing", "match_type": "EXACT"},
    ]


async def test_ad_group_negative_keyword_tools_bound_and_fail_closed(monkeypatch) -> None:
    entry = _writable_google_ads_entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(entry,))),
        tool_name="google_ads_add_ad_group_negative_keywords",
    )
    accepted_client = AsyncMock()
    accepted_client.post.return_value = {
        "results": [{"adGroup": {"id": str(index)}} for index in range(1, 51)]
    }
    provider_add = AsyncMock(
        return_value=mutation_ledger(
            {
                "added": [],
                "resource_names": [],
                "skipped_existing": [
                    {
                        "ad_group_id": str(ad_group_index),
                        "text": f"term {keyword_index}",
                        "match_type": "EXACT",
                    }
                    for ad_group_index in range(1, 51)
                    for keyword_index in range(50)
                ],
                "ad_group_errors": [],
            }
        )
    )

    async def passthrough_audit(_ctx, _entry, **kwargs):
        return (await kwargs["execute"]()).value

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        AsyncMock(return_value=accepted_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.add_ad_group_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.run_audited_integration_operation",
        passthrough_audit,
    )
    accepted = await google_ads_add_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, str(index)) for index in range(1, 51)],
        [NegativeKeywordEntry(text=f"term {index}", match_type="EXACT") for index in range(50)],
    )
    assert accepted.return_value["results"][0]["status"] == "success"
    assert len(provider_add.await_args.kwargs["ad_group_ids"]) == 50
    assert len(provider_add.await_args.kwargs["keywords"]) == 50

    ctx.tool_name = "google_ads_remove_ad_group_negative_keywords"
    provider_client = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        provider_client,
    )

    oversized = await google_ads_remove_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, str(index)) for index in range(1, 7)],
        [
            NegativeKeywordRemovalEntry(text=f"term {index}", match_type="ANY")
            for index in range(500)
        ],
    )

    assert oversized.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "2,500" in oversized.return_value["results"][0]["error_message"]
    provider_client.assert_not_awaited()

    ctx.tool_name = "google_ads_add_ad_group_negative_keywords"
    client = AsyncMock()
    client.post.return_value = {"results": []}
    provider_add = AsyncMock()

    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        AsyncMock(return_value=client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.ad_group_negative_keywords.add_ad_group_negative_keywords",
        provider_add,
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.run_audited_integration_operation",
        passthrough_audit,
    )
    missing = await google_ads_add_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )
    assert missing.return_value["results"][0]["error_code"] == "ModelRetry"
    assert "ad group is unavailable" in missing.return_value["results"][0]["error_message"]
    provider_add.assert_not_awaited()


async def test_ad_group_negative_keyword_write_denial_is_audited_before_provider(
    monkeypatch,
) -> None:
    entry = _writable_google_ads_entry(write_allowed=False)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry,)),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_add_ad_group_negative_keywords",
        tool_call_id="call-add-denied",
    )
    provider_client = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.utils.negative_keyword_tools.google_ads_client",
        provider_client,
    )
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        audit,
    )

    add_result = await google_ads_add_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, "10")],
        [NegativeKeywordEntry(text="term", match_type="EXACT")],
    )
    ctx.tool_name = "google_ads_remove_ad_group_negative_keywords"
    remove_result = await google_ads_remove_ad_group_negative_keywords(
        ctx,
        [_ad_group_reference(entry, "10")],
        [NegativeKeywordRemovalEntry(text="term", match_type="EXACT")],
    )

    assert add_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    assert remove_result.return_value["results"][0]["error_code"] == "write_not_permitted"
    provider_client.assert_not_awaited()
    assert [call.kwargs["operation"] for call in audit.await_args_list] == [
        "add_ad_group_negative_keywords",
        "remove_ad_group_negative_keywords",
    ]
    assert all(call.kwargs["status"] == AuditStatus.FAILURE for call in audit.await_args_list)


def test_campaign_negative_keyword_evidence_is_exact_ordered_and_display_only() -> None:
    entry = _writable_google_ads_entry()
    campaigns = [_campaign_reference(entry, "10"), _campaign_reference(entry, "20")]
    keywords = [
        {"text": "free", "match_type": "EXACT"},
        {"text": "jobs", "match_type": "PHRASE"},
    ]
    ledger = build_keyword_mutation_ledger(
        spec=CAMPAIGN_KEYWORD_MUTATION_SPEC,
        action="add",
        parent_fields=[
            {"campaign_id": campaign.campaign_id, **keyword}
            for campaign in campaigns
            for keyword in keywords
        ],
        skipped_indices={1: "already_exists"},
        submitted=[
            (0, {"campaign_id": "10", **keywords[0]}),
            (2, {"campaign_id": "20", **keywords[0]}),
            (3, {"campaign_id": "20", **keywords[1]}),
        ],
        outcomes=[
            ("applied", "customers/111/campaignCriteria/10~1", None, None),
            ("failed", None, "INVALID_KEYWORD_TEXT", "restricted"),
            ("applied", "customers/111/campaignCriteria/20~4", None, None),
        ],
    )

    display = entity_result(
        "add",
        campaigns,
        ledger,
        max_entities=2,
        include_keyword_outcomes=True,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    model = entity_result(
        "add",
        campaigns,
        ledger,
        max_entities=2,
        include_keyword_outcomes=False,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    pending = pending_operation_detail(
        entry,
        campaigns,
        "add",
        keywords,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    detail = terminal_operation_detail(pending, ledger)

    expected = [
        {
            "text": "free",
            "match_type": "EXACT",
            "outcome": "added",
            "external_ref": "customers/111/campaignCriteria/10~1",
        },
        {"text": "jobs", "match_type": "PHRASE", "outcome": "skipped_existing"},
    ]
    assert display["campaigns"][0]["keyword_outcomes"] == expected
    assert display["campaigns"][1]["keyword_outcomes"] == [
        {
            "text": "free",
            "match_type": "EXACT",
            "outcome": "failed",
            "error_code": "INVALID_KEYWORD_TEXT",
        },
        {
            "text": "jobs",
            "match_type": "PHRASE",
            "outcome": "added",
            "external_ref": "customers/111/campaignCriteria/20~4",
        },
    ]
    assert "keyword_outcomes" not in model["campaigns"][0]
    assert [outcome.status for outcome in detail.outcome_groups[0].outcomes] == [
        "applied",
        "skipped",
    ]
    assert detail.intent_counts.model_dump() == {
        "applied": 2,
        "skipped": 1,
        "failed": 1,
        "unverified": 0,
    }
    assert [len(group.items) for group in pending.intent_groups] == [2, 2]


def test_ad_group_negative_keyword_removal_evidence_attributes_any_expansion() -> None:
    entry = _writable_google_ads_entry()
    ad_groups = [_ad_group_reference(entry, "10"), _ad_group_reference(entry, "20")]
    keywords = [
        {"text": "term", "match_type": "ANY"},
        {"text": "missing", "match_type": "EXACT"},
    ]
    ledger = build_keyword_mutation_ledger(
        spec=AD_GROUP_KEYWORD_MUTATION_SPEC,
        action="remove",
        parent_fields=[
            {"ad_group_id": ad_group.ad_group_id, **keyword}
            for ad_group in ad_groups
            for keyword in keywords
        ],
        skipped_indices={1: "not_found", 3: "not_found"},
        submitted=[
            (0, {"ad_group_id": "10", "text": "term", "match_type": "EXACT"}),
            (0, {"ad_group_id": "10", "text": "term", "match_type": "BROAD"}),
            (2, {"ad_group_id": "20", "text": "Term", "match_type": "PHRASE"}),
        ],
        outcomes=[
            ("failed", None, "CANNOT_REMOVE_CRITERION", "not removed"),
            ("applied", "customers/111/adGroupCriteria/10~2", None, None),
            ("applied", "customers/111/adGroupCriteria/20~3", None, None),
        ],
    )

    display = entity_result(
        "remove",
        ad_groups,
        ledger,
        max_entities=2,
        include_keyword_outcomes=True,
        spec=AD_GROUP_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    pending = pending_operation_detail(
        entry,
        ad_groups,
        "remove",
        keywords,
        spec=AD_GROUP_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    detail = terminal_operation_detail(pending, ledger)

    assert display["ad_groups"][0]["keyword_outcomes"] == [
        {
            "text": "term",
            "match_type": "EXACT",
            "outcome": "failed",
            "error_code": "CANNOT_REMOVE_CRITERION",
        },
        {
            "text": "term",
            "match_type": "BROAD",
            "outcome": "removed",
            "external_ref": "customers/111/adGroupCriteria/10~2",
        },
        {"text": "missing", "match_type": "EXACT", "outcome": "not_found"},
    ]
    assert [effect.status for effect in detail.outcome_groups[0].outcomes[0].effects] == [
        "failed",
        "applied",
    ]
    assert detail.intent_counts.model_dump() == {
        "applied": 1,
        "skipped": 2,
        "failed": 1,
        "unverified": 0,
    }
    assert detail.effect_counts.model_dump() == {
        "applied": 2,
        "skipped": 0,
        "failed": 1,
        "unverified": 0,
    }


def test_campaign_negative_keyword_evidence_rejects_inconsistent_resource_attribution() -> None:
    entry = _writable_google_ads_entry()
    campaigns = [_campaign_reference(entry, "10")]
    keywords = [{"text": "free", "match_type": "EXACT"}]
    pending = pending_operation_detail(
        entry,
        campaigns,
        "add",
        keywords,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    ledger = build_mutation_ledger(
        family="campaign_negative_keywords",
        action="add",
        parent_fields=[{"campaign_id": "20", **keywords[0]}],
        skipped_indices={},
        submitted=[(0, {"campaign_id": "20", **keywords[0]})],
        outcomes=[("applied", "customers/111/campaignCriteria/20~1", None, None)],
        projection=GoogleAdsMutationProjection(
            applied_key="added",
            skipped_key="skipped_existing",
            errors_key="campaign_errors",
        ),
    )

    with pytest.raises(ValueError, match="unknown audit intent"):
        terminal_operation_detail(pending, ledger)


def test_campaign_negative_keyword_maximum_evidence_fits_existing_bounds() -> None:
    entry = _writable_google_ads_entry()
    campaigns = [_campaign_reference(entry, str(index)) for index in range(1, 51)]
    keywords = [
        {"text": f"keyword-{index}-".ljust(80, "x"), "match_type": "EXACT"} for index in range(50)
    ]
    added = [
        {
            "campaign_id": campaign.campaign_id,
            **keyword,
            "resource_name": (
                f"customers/111/campaignCriteria/{campaign.campaign_id}~{keyword_index}"
            ),
        }
        for campaign in campaigns
        for keyword_index, keyword in enumerate(keywords)
    ]
    result = {
        "added": added,
        "resource_names": [item["resource_name"] for item in added],
        "skipped_existing": [],
        "campaign_errors": [],
    }
    ledger = mutation_ledger(result)

    display = entity_result(
        "add",
        campaigns,
        ledger,
        max_entities=50,
        include_keyword_outcomes=True,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    pending = pending_operation_detail(
        entry,
        campaigns,
        "add",
        keywords,
        spec=CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
    )
    detail = terminal_operation_detail(pending, ledger)
    display_bytes = len(json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode())
    detail_bytes = len(
        json.dumps(
            detail.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
        ).encode()
    )

    assert sum(len(row["keyword_outcomes"]) for row in display["campaigns"]) == 2_500
    assert sum(len(group.outcomes) for group in detail.outcome_groups) == 2_500
    assert display_bytes < MAX_CAMPAIGN_NEGATIVE_PUBLIC_RESULT_CHARS
    assert detail_bytes < MAX_INTEGRATION_OPERATION_DETAIL_BYTES
