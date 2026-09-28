"""Google Ads positive-keyword action contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.create_positive_keywords import (
    GoogleAdsPositiveKeywordCreate,
    create_positive_keywords,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
)
from integrations.google_ads.tools.create_positive_keywords import (
    DEFINITION,
    _KeywordCreateContext,
    _validate_bid_compatibility,
    google_ads_create_keywords,
)
from integrations.google_ads.tools.schemas import (
    GoogleAdsCreatePositiveKeywordsOutput,
    GoogleAdsPositiveKeywordEntry,
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
            "finalUrls": ["https://existing.example.com"],
            "keyword": {"text": text, "matchType": match_type},
        },
    }


def test_positive_keyword_schema_normalizes_only_whitespace_and_validates_provider_bounds() -> None:
    row = GoogleAdsPositiveKeywordEntry(
        text="  Running\t Shoes  ", match_type="PHRASE", cpc_bid="01.250000"
    )
    exact_maximum = GoogleAdsPositiveKeywordEntry(
        text="shoes", match_type="EXACT", cpc_bid="9223372036854.775807"
    )

    assert row.text == "Running Shoes"
    assert row.cpc_bid == "01.250000"
    assert row.match_type == "PHRASE"
    assert exact_maximum.cpc_bid == "9223372036854.775807"
    with pytest.raises(ValidationError, match="at most 10 words"):
        GoogleAdsPositiveKeywordEntry(
            text="one two three four five six seven eight nine ten eleven",
            match_type="BROAD",
        )
    for overprecise in ("1.0000000", "1.0000001"):
        with pytest.raises(ValidationError, match="six decimal places"):
            GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid=overprecise)
    for unsupported in (".5", "1."):
        with pytest.raises(ValidationError, match="positive decimal number"):
            GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid=unsupported)
    with pytest.raises(ValidationError, match="too large"):
        GoogleAdsPositiveKeywordEntry(
            text="shoes", match_type="EXACT", cpc_bid="9223372036854.775808"
        )
    assert (
        GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid="").cpc_bid is None
    )


async def test_create_positive_keywords_sends_every_requested_provider_field() -> None:
    client = SequencedClient(
        [{"results": [{"resourceName": "customers/333/adGroupCriteria/20~91"}]}]
    )
    await create_positive_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        existing_rows=[],
        creates=[
            GoogleAdsPositiveKeywordCreate(
                ad_group_id="20",
                text="trail shoes",
                match_type="PHRASE",
                status="PAUSED",
                cpc_bid_micros=2_500_000,
                final_urls=("https://example.com/trail",),
                final_mobile_urls=("https://m.example.com/trail",),
                final_url_suffix="source=ads",
                tracking_url_template="https://track.example.com/{lpurl}",
                url_custom_parameters=(("audience", "trail"),),
            )
        ],
    )

    create = client.calls[0][1]["json"]["operations"][0]["create"]
    assert create == {
        "adGroup": "customers/333/adGroups/20",
        "status": "PAUSED",
        "negative": False,
        "keyword": {"text": "trail shoes", "matchType": "PHRASE"},
        "cpcBidMicros": "2500000",
        "finalUrls": ["https://example.com/trail"],
        "finalMobileUrls": ["https://m.example.com/trail"],
        "finalUrlSuffix": "source=ads",
        "trackingUrlTemplate": "https://track.example.com/{lpurl}",
        "urlCustomParameters": [{"key": "audience", "value": "trail"}],
    }


@pytest.mark.parametrize(
    ("channel", "ad_group_type"),
    [
        pytest.param("SHOPPING", "SHOPPING_PRODUCT_ADS", id="shopping-listing-groups"),
        pytest.param("VIDEO", "VIDEO_TRUE_VIEW_IN_STREAM", id="video-no-keyword-target"),
    ],
)
def test_v24_positive_keyword_eligibility_matrix_rejects_unsupported_targets_without_a_bid(
    channel: str, ad_group_type: str
) -> None:
    with pytest.raises(ModelRetry, match="cannot accept positive keyword criteria"):
        _validate_bid_compatibility(
            {
                "20": _KeywordCreateContext(
                    strategy="MANUAL_CPC",
                    channel=channel,
                    ad_group_type=ad_group_type,
                    display_custom_bid_dimension="",
                )
            },
            [GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT")],
        )


@pytest.mark.parametrize("dimension", ["PLACEMENT"])
def test_display_absolute_keyword_bid_requires_keyword_dimension(dimension: str) -> None:
    with pytest.raises(ModelRetry, match="custom bid dimension"):
        _validate_bid_compatibility(
            {
                "20": _KeywordCreateContext(
                    strategy="MANUAL_CPC",
                    channel="DISPLAY",
                    ad_group_type="DISPLAY_STANDARD",
                    display_custom_bid_dimension=dimension,
                )
            },
            [GoogleAdsPositiveKeywordEntry(text="shoes", match_type="BROAD", cpc_bid="2")],
        )


async def test_create_positive_keywords_skips_existing_pair_and_sends_optional_bid() -> None:
    client = SequencedClient(
        [
            [{"results": [existing_row("RUNNING SHOES")]}],
            [{"results": []}],
            {"results": [{"resourceName": "customers/333/adGroupCriteria/20~91"}]},
        ]
    )
    ledger = await create_positive_keywords(
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


async def test_create_positive_keywords_keeps_partial_failure_and_ambiguity_distinct() -> None:
    rejected = await create_positive_keywords(
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
    ambiguous = await create_positive_keywords(
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
                            "campaign": {
                                "id": "10",
                                "name": "Search",
                                "advertisingChannelType": "SEARCH",
                                "biddingStrategyType": "MANUAL_CPC",
                            },
                            "adGroup": {
                                "id": "20",
                                "name": "Shoes",
                                "status": "ENABLED",
                                "type": "SEARCH_STANDARD",
                            },
                        }
                    ]
                }
            ],
            [{"results": [existing_row("running   shoes")]}],
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
        "integrations.google_ads.tools.create_positive_keywords.google_ads_client",
        AsyncMock(return_value=provider_client),
    )
    monkeypatch.setattr(
        "integrations.google_ads.tools.create_positive_keywords.run_audited_integration_operation",
        passthrough_audit,
    )
    result = await google_ads_create_keywords(
        ctx,
        [ad_group()],
        [
            GoogleAdsPositiveKeywordEntry(text="running shoes", match_type="EXACT"),
            GoogleAdsPositiveKeywordEntry(text="trail shoes", match_type="PHRASE", cpc_bid="2.5"),
        ],
    )

    model_output = GoogleAdsCreatePositiveKeywordsOutput.model_validate(result.return_value)
    display_output = GoogleAdsCreatePositiveKeywordsOutput.model_validate(
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
    assert skipped.requested.status == "ENABLED"
    assert skipped.observed is not None
    assert skipped.observed.status == "PAUSED"
    assert skipped.observed.cpc_bid == "1.25"
    assert skipped.observed.final_urls == ["https://existing.example.com"]
    assert skipped.ad_group_name == "Shoes"
    assert added.previous_state == "absent"
    assert added.requested.cpc_bid == "2.5"
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
