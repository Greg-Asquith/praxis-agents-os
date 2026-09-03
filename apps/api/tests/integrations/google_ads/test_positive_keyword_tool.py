"""Google Ads positive-keyword action contracts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.add_positive_keywords import (
    GoogleAdsPositiveKeywordCreate,
    add_positive_keywords,
    positive_keyword_creation_failure_ledger,
)
from integrations.google_ads.references import GoogleAdsAdGroupReference, GoogleAdsKeywordReference
from integrations.google_ads.tools.add_positive_keywords import (
    DEFINITION,
    _approval_display_args,
    _pending_operation_detail,
    google_ads_add_keywords,
)
from integrations.google_ads.tools.schemas import (
    GoogleAdsAddPositiveKeywordsOutput,
    GoogleAdsPositiveKeywordEntry,
)
from integrations.google_ads.tools.utils.mutation_evidence import terminal_operation_detail
from integrations.google_ads.tools.utils.positive_keyword_results import (
    MAX_POSITIVE_KEYWORD_DISPLAY_CHARS,
    display_positive_keyword_result,
)
from services.audit_events.integration_operation_detail import (
    MAX_INTEGRATION_OPERATION_DETAIL_BYTES,
)
from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry
from services.integrations.http import IntegrationRequestPolicy


class SequencedClient:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = []

    async def post(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return next(self.payloads)


def entry() -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="google_ads",
        resource_type="google_ads_account",
        external_id="333",
        display_name="Retail account",
        connection_id=uuid4(),
        connection_label="Google Ads",
        connection_status="active",
        write_allowed=True,
        permissions_metadata={"login_customer_id": "111", "currency_code": "GBP"},
    )


def ad_group(ad_group_id: str = "20") -> GoogleAdsAdGroupReference:
    return GoogleAdsAdGroupReference(
        customer_id="333",
        campaign_id="10",
        ad_group_id=ad_group_id,
        label=f"Stale ad group {ad_group_id}",
        scope_label="Stale campaign",
    )


def existing_row(
    text: str = "running shoes",
    *,
    match_type: str = "EXACT",
    criterion_id: str = "90",
    status: str = "PAUSED",
) -> dict:
    return {
        "campaign": {"id": "10", "name": "Search"},
        "adGroup": {"id": "20", "name": "Shoes", "status": "ENABLED"},
        "adGroupCriterion": {
            "resourceName": f"customers/333/adGroupCriteria/20~{criterion_id}",
            "criterionId": criterion_id,
            "status": status,
            "cpcBidMicros": "1250000",
            "keyword": {"text": text, "matchType": match_type},
        },
    }


def test_positive_keyword_schema_normalizes_only_whitespace_and_validates_provider_bounds() -> None:
    row = GoogleAdsPositiveKeywordEntry(
        text="  Running\t Shoes  ", match_type="PHRASE", cpc_bid="01.250000"
    )

    assert row.text == "Running Shoes"
    assert row.cpc_bid == "01.250000"
    assert row.match_type == "PHRASE"
    with pytest.raises(ValidationError, match="at most 10 words"):
        GoogleAdsPositiveKeywordEntry(
            text="one two three four five six seven eight nine ten eleven",
            match_type="BROAD",
        )
    with pytest.raises(ValidationError, match="six decimal places"):
        GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid="1.0000001")
    for unsupported in (".5", "1."):
        with pytest.raises(ValidationError, match="positive decimal number"):
            GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid=unsupported)
    assert (
        GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid="").cpc_bid is None
    )


def test_keyword_reference_accepts_resource_name_and_serializes_int64_bid_exactly() -> None:
    reference = GoogleAdsKeywordReference(
        customer_id="333",
        campaign_id="10",
        ad_group_id="20",
        criterion_id="customers/333/adGroupCriteria/20~90",
        text="running shoes",
        match_type="EXACT",
        status="ENABLED",
        cpc_bid_micros=9_007_199_254_740_993,
        label="running shoes",
    )

    assert reference.criterion_id == "90"
    assert reference.model_dump(mode="json")["cpc_bid_micros"] == "9007199254740993"
    with pytest.raises(ValidationError, match="belong to its ad group"):
        reference.model_validate(
            {**reference.model_dump(), "criterion_id": "customers/333/adGroupCriteria/21~90"}
        )


async def test_add_positive_keywords_skips_existing_pair_and_sends_optional_bid() -> None:
    client = SequencedClient(
        [
            [{"results": [existing_row("RUNNING SHOES")]}],
            [{"results": []}],
            {"results": [{"resourceName": "customers/333/adGroupCriteria/20~91"}]},
        ]
    )
    ledger = await add_positive_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        creates=[
            GoogleAdsPositiveKeywordCreate("20", "running shoes", "EXACT"),
            GoogleAdsPositiveKeywordCreate("20", "trail shoes", "PHRASE", 2_500_000),
        ],
    )

    assert ledger.intent_counts == {"requested": 2, "submitted": 1, "skipped": 1}
    assert ledger.effect_counts == {"applied": 1, "failed": 0, "unverified": 0}
    search_path, search_kwargs = client.calls[0]
    assert search_path == "customers/333/googleAds:searchStream"
    assert "ad_group_criterion.negative = FALSE" in search_kwargs["json"]["query"]
    assert "REGEXP_MATCH '(?i)^(?:running shoes)$'" in search_kwargs["json"]["query"]
    assert "keyword.match_type IN ('EXACT')" in search_kwargs["json"]["query"]
    assert "keyword.match_type IN ('PHRASE')" in client.calls[1][1]["json"]["query"]
    mutate_path, mutate_kwargs = client.calls[2]
    assert mutate_path == "customers/333/adGroupCriteria:mutate"
    assert mutate_kwargs["policy"] is IntegrationRequestPolicy.MUTATION
    assert mutate_kwargs["json"] == {
        "operations": [
            {
                "create": {
                    "adGroup": "customers/333/adGroups/20",
                    "status": "ENABLED",
                    "negative": False,
                    "keyword": {"text": "trail shoes", "matchType": "PHRASE"},
                    "cpcBidMicros": "2500000",
                }
            }
        ],
        "partialFailure": True,
    }


async def test_add_positive_keywords_ignores_mismatched_existing_resource() -> None:
    mismatched = existing_row()
    mismatched["adGroupCriterion"]["resourceName"] = "customers/999/adGroupCriteria/20~90"
    client = SequencedClient(
        [
            [{"results": [mismatched]}],
            {"results": [{"resourceName": "customers/333/adGroupCriteria/20~91"}]},
        ]
    )

    ledger = await add_positive_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        creates=[GoogleAdsPositiveKeywordCreate("20", "running shoes", "EXACT")],
    )

    assert ledger.intent_counts == {"requested": 1, "submitted": 1, "skipped": 0}
    assert len(client.calls[1][1]["json"]["operations"]) == 1


async def test_add_positive_keywords_keeps_partial_failure_and_ambiguity_distinct() -> None:
    rejected = await add_positive_keywords(
        SequencedClient(
            [
                [{"results": []}],
                [{"results": []}],
                {
                    "results": [
                        {"resourceName": "customers/333/adGroupCriteria/20~91"},
                        {},
                    ],
                    "partialFailureError": {
                        "details": [
                            {
                                "errors": [
                                    {
                                        "message": "Bid incompatible with ad group",
                                        "errorCode": {
                                            "adGroupCriterionError": "BID_INCOMPATIBLE_WITH_ADGROUP"
                                        },
                                        "location": {
                                            "fieldPathElements": [
                                                {"fieldName": "operations", "index": 1}
                                            ]
                                        },
                                    }
                                ]
                            }
                        ]
                    },
                },
            ]
        ),
        customer_id="333",
        login_customer_id="111",
        creates=[
            GoogleAdsPositiveKeywordCreate("20", "running shoes", "EXACT"),
            GoogleAdsPositiveKeywordCreate("20", "trail shoes", "PHRASE", 2_500_000),
        ],
    )
    ambiguous = await add_positive_keywords(
        SequencedClient(
            [
                [{"results": []}],
                {"results": [{"resourceName": "customers/999/adGroupCriteria/20~91"}]},
            ]
        ),
        customer_id="333",
        login_customer_id="111",
        creates=[GoogleAdsPositiveKeywordCreate("20", "running shoes", "EXACT")],
    )

    assert [effect.outcome for effect in rejected.effects] == ["applied", "failed"]
    assert rejected.effects[1].error_code == "BID_INCOMPATIBLE_WITH_ADGROUP"
    assert ambiguous.effects[0].outcome == "unverified"


def test_add_positive_keyword_definition_is_approval_only_without_selection_advice() -> None:
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    assert "does not select, recommend, or classify" in DEFINITION.description
    fields = {field.key: field for field in DEFINITION.presentation.arg_fields}
    assert fields["ad_groups"].entity_kind == "google_ads_ad_group"
    assert fields["keywords"].format == "records"
    assert fields["keywords"].columns[2].key == "cpc_bid"


async def test_add_positive_keyword_tool_uses_live_targets_and_returns_exact_rows(
    monkeypatch,
) -> None:
    selected = entry()
    ctx = SimpleNamespace(
        deps=SimpleNamespace(active_context=ResolvedActiveContext(entries=(selected,))),
        tool_name=DEFINITION.name,
    )
    provider_client = SequencedClient(
        [
            [
                {
                    "results": [
                        {
                            "campaign": {"id": "10", "name": "Search"},
                            "adGroup": {"id": "20", "name": "Shoes", "status": "ENABLED"},
                        }
                    ]
                }
            ],
            [{"results": [existing_row()]}],
            [{"results": []}],
            {"results": [{"resourceName": "customers/333/adGroupCriteria/20~91"}]},
        ]
    )
    audit_outcomes = []

    async def passthrough_audit(_ctx, _entry, **kwargs):
        await kwargs["prepare_pending_operation"]()
        outcome = await kwargs["execute"]()
        audit_outcomes.append(outcome)
        return outcome.value

    monkeypatch.setattr(
        "integrations.google_ads.tools.add_positive_keywords.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_positive_keywords.run_audited_integration_operation",
        passthrough_audit,
    )
    result = await google_ads_add_keywords(
        ctx,
        [ad_group()],
        [
            GoogleAdsPositiveKeywordEntry(text="running shoes", match_type="EXACT"),
            GoogleAdsPositiveKeywordEntry(text="trail shoes", match_type="PHRASE", cpc_bid="2.5"),
        ],
    )

    model_output = GoogleAdsAddPositiveKeywordsOutput.model_validate(result.return_value)
    display_output = GoogleAdsAddPositiveKeywordsOutput.model_validate(
        result.metadata["public_result"]
    )
    data = display_output.results[0].data
    assert data is not None, result.metadata["public_result"]
    assert data.counts.model_dump() == {
        "added": 1,
        "skipped_existing": 1,
        "failed": 0,
        "unverified": 0,
    }
    skipped = data.samples.skipped_existing[0]
    added = data.samples.added[0]
    assert skipped.previous_state == "existing"
    assert skipped.keyword is None
    assert skipped.ad_group_name == "Shoes"
    assert added.previous_state == "absent"
    assert added.cpc_bid == "2.5"
    assert added.keyword is None
    model_data = model_output.results[0].data
    assert model_data is not None
    assert model_data.samples.skipped_existing[0].keyword is not None
    assert model_data.samples.skipped_existing[0].keyword.status == "PAUSED"
    assert model_data.samples.added[0].keyword is not None
    assert model_data.samples.added[0].keyword.criterion_id == "91"
    detail = audit_outcomes[0].operation_detail
    assert detail.intent_counts.applied == 1
    assert detail.intent_counts.skipped == 1
    assert detail.effect_counts.applied == 1


def test_positive_keyword_approval_projection_fills_optional_record_cells() -> None:
    projected = _approval_display_args(
        SimpleNamespace(
            active_context=ResolvedActiveContext(entries=(entry(),)),
        ),
        {
            "ad_groups": [ad_group().model_dump(mode="json")],
            "keywords": [{"text": "running shoes", "match_type": "EXACT"}],
        },
    )

    assert projected["keywords"] == [
        {"text": "running shoes", "match_type": "EXACT", "cpc_bid": ""}
    ]


async def test_maximum_positive_keyword_terminal_evidence_stays_bounded() -> None:
    selected = entry()
    groups = [
        GoogleAdsAdGroupReference(
            customer_id="333",
            campaign_id=str(index + 1),
            ad_group_id=str(index + 1),
            label="a" * 100,
            scope_label="c" * 100,
        )
        for index in range(50)
    ]
    keywords = [
        GoogleAdsPositiveKeywordEntry(
            text=f"{index:03d}{'k' * 77}",
            match_type="BROAD",
            cpc_bid="9223372036854.775807",
        )
        for index in range(50)
    ]
    pending = _pending_operation_detail(selected, groups, keywords)
    creates = [
        GoogleAdsPositiveKeywordCreate(
            group.ad_group_id,
            keyword.text,
            keyword.match_type,
            9_223_372_036_854_775_807,
        )
        for group in groups
        for keyword in keywords
    ]
    ledger = await add_positive_keywords(
        SequencedClient(
            [
                {
                    "results": [
                        {
                            "resourceName": (
                                f"customers/333/adGroupCriteria/{create.ad_group_id}~{index + 1}"
                            )
                        }
                        for index, create in enumerate(creates)
                    ]
                }
            ]
        ),
        customer_id="333",
        login_customer_id="111",
        creates=creates,
        existing_rows=[],
    )

    detail = terminal_operation_detail(
        pending,
        ledger,
        identity_keys=("ad_group_id", "text", "match_type"),
    )
    failure_detail = terminal_operation_detail(
        pending,
        positive_keyword_creation_failure_ledger(
            creates,
            customer_id="333",
            outcome="failed",
            error_code="E" * 100,
            message="m" * 1_000,
        ),
        identity_keys=("ad_group_id", "text", "match_type"),
    )
    for terminal_detail in (detail, failure_detail):
        serialized = json.dumps(
            terminal_detail.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        assert len(serialized) <= MAX_INTEGRATION_OPERATION_DETAIL_BYTES


async def test_add_positive_keyword_tool_rejects_duplicate_rows_and_product_overflow(
    monkeypatch,
) -> None:
    targeting = AsyncMock()
    monkeypatch.setattr(
        "integrations.google_ads.tools.add_positive_keywords.run_context_targets", targeting
    )
    duplicate = GoogleAdsPositiveKeywordEntry(text="running shoes", match_type="EXACT")
    with pytest.raises(ModelRetry, match="can appear only once"):
        await google_ads_add_keywords(None, [ad_group()], [duplicate, duplicate])  # type: ignore[arg-type]
    groups = [ad_group(str(index + 1)) for index in range(50)]
    keywords = [
        GoogleAdsPositiveKeywordEntry(text=f"keyword {index}", match_type="EXACT")
        for index in range(51)
    ]
    with pytest.raises(ModelRetry, match="must not exceed 2,500"):
        await google_ads_add_keywords(None, groups, keywords)  # type: ignore[arg-type]
    targeting.assert_not_awaited()


def test_positive_keyword_display_keeps_every_maximum_fanout_row_bounded() -> None:
    rows = [
        {
            "campaign_id": "1",
            "campaign_name": "c" * 100,
            "ad_group_id": str(index + 1),
            "ad_group_name": "a" * 100,
            "text": "k" * 80,
            "match_type": "BROAD",
            "cpc_bid": "9223372036854.775807",
            "cpc_bid_micros": "9223372036854775807",
            "previous_state": "absent",
            "outcome": "failed",
            "error_code": "E" * 100,
            "message": "m" * 200,
        }
        for index in range(2_500)
    ]

    result = display_positive_keyword_result(rows, currency_code="GBP")

    assert len(result["samples"]["failed"]) == 2_500
    assert result["samples_truncated"] is False
    assert len(json.dumps(result, separators=(",", ":"))) < MAX_POSITIVE_KEYWORD_DISPLAY_CHARS
