"""Google Ads campaign and ad-group negative-keyword tool contracts."""

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
    CAMPAIGN_KEYWORD_MUTATION_SPEC,
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_keyword_mutation_ledger,
    build_mutation_ledger,
)
from integrations.google_ads.tools.add_campaign_negative_keywords import (
    google_ads_add_campaign_negative_keywords,
)
from integrations.google_ads.tools.remove_campaign_negative_keywords import (
    google_ads_remove_campaign_negative_keywords,
)
from integrations.google_ads.tools.schemas.negative_keyword import (
    NegativeKeywordEntry,
    NegativeKeywordRemovalEntry,
)
from integrations.google_ads.tools.utils.campaign_negative_keywords import (
    CAMPAIGN_NEGATIVE_KEYWORD_TOOL_SPEC,
)
from integrations.google_ads.tools.utils.mutation_evidence import terminal_operation_detail
from integrations.google_ads.tools.utils.negative_keyword_tools import (
    entity_result,
    pending_operation_detail,
)
from services.audit_events import AuditStatus
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import (
    _AdGroupNegativeKeywordClient,
    _campaign_reference,
    _CampaignNegativeKeywordClient,
    _writable_google_ads_entry,
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
                {"resourceName": f"customers/3333333333/{criterion_path}/20~2"},
                {},
                {"resourceName": f"customers/3333333333/{criterion_path}/10~3"},
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
