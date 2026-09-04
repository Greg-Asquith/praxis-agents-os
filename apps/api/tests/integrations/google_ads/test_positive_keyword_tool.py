"""Google Ads positive-keyword action contracts."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry

from integrations.google_ads.operations.create_positive_keywords import (
    GoogleAdsPositiveKeywordCreate,
    create_positive_keywords,
    positive_keyword_creation_failure_ledger,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsKeywordReference,
    positive_keyword_reference_from_row,
)
from integrations.google_ads.tools.create_positive_keywords import (
    DEFINITION,
    _approval_display_args,
    _KeywordCreateContext,
    _pending_operation_detail,
    _validate_bid_compatibility,
    google_ads_create_keywords,
)
from integrations.google_ads.tools.schemas import (
    GoogleAdsCreatePositiveKeywordsOutput,
    GoogleAdsPositiveKeywordEntry,
)
from integrations.google_ads.tools.utils.mutation_evidence import terminal_operation_detail
from integrations.google_ads.tools.utils.positive_keyword_results import (
    MAX_POSITIVE_KEYWORD_DISPLAY_CHARS,
    MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS,
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


@pytest.mark.parametrize(
    ("field", "accepted"),
    [
        pytest.param("cpc_bid", True, id="cpc-custom-bid"),
        pytest.param("bid_modifier", False, id="keyword-bid-adjustment-prohibited"),
        pytest.param("cpm_bid", False, id="keyword-cpm-explicitly-unsupported"),
        pytest.param("cpv_bid", False, id="cpv-requires-non-keyword-video-target"),
        pytest.param(
            "percent_cpc_bid",
            False,
            id="percent-cpc-requires-hotel-listing-group",
        ),
    ],
)
def test_v24_positive_keyword_bid_field_contract(field: str, accepted: bool) -> None:
    # Sources: v24 AdGroupCriterion, AdGroupCriterionError, criterion-simulation
    # combinations, manual-bidding guidance, and Hotel bidding guidance. Google
    # Ads permits keyword custom bids but prohibits keyword bid adjustments;
    # keyword CPM is explicitly unsupported, while CPV and Percent CPC belong to
    # campaign/criterion combinations that do not accept positive keywords.
    fields = {"text": "shoes", "match_type": "EXACT", field: "1"}
    if accepted:
        assert GoogleAdsPositiveKeywordEntry(**fields).cpc_bid == "1"
    else:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            GoogleAdsPositiveKeywordEntry(**fields)


def test_positive_keyword_schema_accepts_every_create_field_and_bounds_nested_values() -> None:
    row = GoogleAdsPositiveKeywordEntry(
        text="trail shoes",
        match_type="PHRASE",
        status="PAUSED",
        cpc_bid="2.5",
        final_urls=["https://example.com/trail"],
        final_mobile_urls=["https://m.example.com/trail"],
        final_url_suffix="source=ads",
        tracking_url_template="https://track.example.com/{lpurl}",
        url_custom_parameters={"audience": "trail"},
    )

    assert row.status == "PAUSED"
    assert row.url_custom_parameters == {"audience": "trail"}
    with pytest.raises(ValidationError, match="at most 10 items"):
        row.model_validate({**row.model_dump(), "final_urls": ["https://example.com"] * 11})
    with pytest.raises(ValidationError, match="at most 8"):
        row.model_validate(
            {
                **row.model_dump(),
                "url_custom_parameters": {f"key{index}": "v" for index in range(9)},
            }
        )
    with pytest.raises(ValidationError, match="HTTP or HTTPS"):
        row.model_validate({**row.model_dump(), "final_urls": ["javascript:alert(1)"]})
    with pytest.raises(ValidationError, match="at least one final URL"):
        GoogleAdsPositiveKeywordEntry(
            text="shoes",
            match_type="EXACT",
            tracking_url_template="https://track.example.com/{lpurl}",
        )
    assert GoogleAdsPositiveKeywordEntry(
        text="shoes", match_type="EXACT", final_urls=["https://example.com"]
    )


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"promo_code": "x"}, "ASCII letters or numbers"),
        ({"promoCode": "x", "promocode": "y"}, "unique, ignoring case"),
        ({"a" * 17: "x"}, "1-16"),
        ({"a": "🙂" * 51}, "200 UTF-8 bytes"),
        ({f"key{index}": "x" for index in range(9)}, "at most 8"),
    ],
)
def test_positive_keyword_custom_parameters_reject_provider_invalid_values(
    parameters: dict[str, str], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        GoogleAdsPositiveKeywordEntry(
            text="shoes", match_type="EXACT", url_custom_parameters=parameters
        )


def test_positive_keyword_custom_parameter_byte_boundaries_and_prototype_name() -> None:
    parameters = {"a" * 16: "🙂" * 50, "constructor": "value"}
    row = GoogleAdsPositiveKeywordEntry(
        text="shoes", match_type="EXACT", url_custom_parameters=parameters
    )
    assert row.url_custom_parameters == parameters


def test_positive_keyword_reference_parser_fails_closed_for_invalid_provider_fields() -> None:
    valid = existing_row()
    valid["adGroupCriterion"]["urlCustomParameters"] = [{"key": "constructor", "value": "🙂" * 50}]
    reference = positive_keyword_reference_from_row("333", valid)
    assert reference is not None
    assert reference.url_custom_parameters[0].key == "constructor"

    invalid_rows = []
    for field, value in (
        ("urlCustomParameters", [{"key": "promo_code", "value": "x"}]),
        (
            "urlCustomParameters",
            [{"key": "promoCode", "value": "x"}, {"key": "promocode", "value": "y"}],
        ),
        ("urlCustomParameters", [{"key": "a", "value": "🙂" * 51}]),
        ("finalUrlSuffix", "x" * 2049),
        ("finalUrlSuffix", 123),
        ("trackingUrlTemplate", []),
        ("cpcBidMicros", str(2**63)),
        ("cpcBidMicros", 1.5),
        ("bidModifier", "not-a-number"),
    ):
        row = existing_row()
        row["adGroupCriterion"][field] = value
        invalid_rows.append(row)
    long_text = existing_row()
    long_text["adGroupCriterion"]["keyword"]["text"] = "x" * 81
    invalid_rows.append(long_text)
    long_url = existing_row()
    long_url["adGroupCriterion"]["finalUrls"] = [f"https://example.com/{'x' * 2030}"]
    invalid_rows.append(long_url)
    invalid_url = existing_row()
    invalid_url["adGroupCriterion"]["finalUrls"] = ["javascript:alert(1)"]
    invalid_rows.append(invalid_url)
    assert all(positive_keyword_reference_from_row("333", row) is None for row in invalid_rows)


def test_positive_keyword_reference_validates_custom_parameters_when_built_directly() -> None:
    fields = {
        "customer_id": "333",
        "campaign_id": "10",
        "ad_group_id": "20",
        "criterion_id": "90",
        "text": "running shoes",
        "match_type": "EXACT",
        "status": "ENABLED",
        "label": "running shoes",
    }
    with pytest.raises(ValidationError, match="unique, ignoring case"):
        GoogleAdsKeywordReference(
            **fields,
            url_custom_parameters=[
                {"key": "promoCode", "value": "x"},
                {"key": "promocode", "value": "y"},
            ],
        )
    with pytest.raises(ValidationError, match="200 UTF-8 bytes"):
        GoogleAdsKeywordReference(
            **fields,
            url_custom_parameters=[{"key": "promo", "value": "🙂" * 51}],
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


async def test_create_positive_keywords_defensively_requires_a_final_url_for_tracking() -> None:
    client = SequencedClient([])
    with pytest.raises(ValueError, match="require at least one final URL"):
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
                    tracking_url_template="https://track.example.com/{lpurl}",
                )
            ],
        )

    with pytest.raises(ValueError, match="ASCII letters or numbers"):
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
                    url_custom_parameters=(("promo_code", "x"),),
                )
            ],
        )


@pytest.mark.parametrize(
    ("channel", "ad_group_type", "strategy", "dimension", "cpc_bid"),
    [
        pytest.param(
            "SEARCH", "SEARCH_STANDARD", "TARGET_CPA", "", None, id="search-no-custom-bid"
        ),
        pytest.param(
            "SEARCH", "SEARCH_STANDARD", "MANUAL_CPC", "", "1", id="search-cpc-custom-bid"
        ),
        pytest.param(
            "DISPLAY",
            "DISPLAY_STANDARD",
            "TARGET_CPA",
            "PLACEMENT",
            None,
            id="display-no-custom-bid",
        ),
        pytest.param(
            "DISPLAY",
            "DISPLAY_STANDARD",
            "MANUAL_CPC",
            "KEYWORD",
            "1",
            id="display-cpc-keyword-dimension",
        ),
    ],
)
def test_v24_positive_keyword_eligibility_matrix_allows_supported_targets(
    channel: str,
    ad_group_type: str,
    strategy: str,
    dimension: str,
    cpc_bid: str | None,
) -> None:
    # v24 documents standard Search/Display ad-group structures and only
    # SEARCH/DISPLAY + KEYWORD + CPC_BID criterion simulations.
    _validate_bid_compatibility(
        {
            "20": _KeywordCreateContext(
                strategy=strategy,
                channel=channel,
                ad_group_type=ad_group_type,
                display_custom_bid_dimension=dimension,
            )
        },
        [GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid=cpc_bid)],
    )


@pytest.mark.parametrize(
    ("channel", "ad_group_type"),
    [
        pytest.param("SEARCH", "SEARCH_STANDARD", id="search-keyword-urls"),
        pytest.param("DISPLAY", "DISPLAY_STANDARD", id="display-keyword-urls"),
    ],
)
def test_v24_positive_keyword_urls_are_available_for_each_supported_target(
    channel: str, ad_group_type: str
) -> None:
    # The upgraded-URL supported-entities matrix permits final URLs, final
    # mobile URLs, custom parameters, and tracking templates on AdGroupCriterion.
    keyword = GoogleAdsPositiveKeywordEntry(
        text="shoes",
        match_type="EXACT",
        final_urls=["https://example.com/shoes"],
        final_mobile_urls=["https://m.example.com/shoes"],
        final_url_suffix="source=ads",
        tracking_url_template="https://track.example.com/{lpurl}",
        url_custom_parameters={"audience": "shoes"},
    )
    _validate_bid_compatibility(
        {
            "20": _KeywordCreateContext(
                strategy="TARGET_CPA",
                channel=channel,
                ad_group_type=ad_group_type,
                display_custom_bid_dimension="",
            )
        },
        [keyword],
    )


@pytest.mark.parametrize(
    ("channel", "ad_group_type"),
    [
        pytest.param("SHOPPING", "SHOPPING_PRODUCT_ADS", id="shopping-listing-groups"),
        pytest.param("HOTEL", "HOTEL_ADS", id="hotel-listing-groups"),
        pytest.param("VIDEO", "VIDEO_TRUE_VIEW_IN_STREAM", id="video-no-keyword-target"),
        pytest.param("SEARCH", "SEARCH_DYNAMIC_ADS", id="dynamic-search-webpage-target"),
        pytest.param("DISPLAY", "UNKNOWN", id="unknown-display-ad-group-type"),
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


@pytest.mark.parametrize("dimension", ["PLACEMENT", "TOPIC", "", "UNKNOWN", "UNSPECIFIED"])
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


@pytest.mark.parametrize("ad_group_type", ["", "UNKNOWN", "UNSPECIFIED"])
def test_keyword_bid_rejects_unknown_ad_group_type(ad_group_type: str) -> None:
    with pytest.raises(ModelRetry, match="cannot accept positive keyword criteria"):
        _validate_bid_compatibility(
            {
                "20": _KeywordCreateContext(
                    strategy="MANUAL_CPC",
                    channel="SEARCH",
                    ad_group_type=ad_group_type,
                    display_custom_bid_dimension="",
                )
            },
            [GoogleAdsPositiveKeywordEntry(text="shoes", match_type="EXACT", cpc_bid="1")],
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


async def test_create_positive_keywords_ignores_mismatched_existing_resource() -> None:
    mismatched = existing_row()
    mismatched["adGroupCriterion"]["resourceName"] = "customers/999/adGroupCriteria/20~90"
    client = SequencedClient(
        [
            [{"results": [mismatched]}],
            {"results": [{"resourceName": "customers/333/adGroupCriteria/20~91"}]},
        ]
    )

    ledger = await create_positive_keywords(
        client,
        customer_id="333",
        login_customer_id="111",
        creates=[GoogleAdsPositiveKeywordCreate("20", "running shoes", "EXACT")],
    )

    assert ledger.intent_counts == {"requested": 1, "submitted": 1, "skipped": 0}
    assert len(client.calls[1][1]["json"]["operations"]) == 1


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


def test_add_positive_keyword_definition_is_approval_only_without_selection_advice() -> None:
    assert DEFINITION.default_policy == "approval"
    assert DEFINITION.supports_auto is False
    assert DEFINITION.code_eligible is True
    assert "does not select, recommend, or classify" in DEFINITION.description
    fields = {field.key: field for field in DEFINITION.presentation.arg_fields}
    assert fields["ad_groups"].entity_kind == "google_ads_ad_group"
    assert fields["keywords"].format == "records"
    assert [column.key for column in fields["keywords"].columns] == [
        "text",
        "match_type",
        "status",
        "cpc_bid",
        "final_urls",
        "final_mobile_urls",
        "final_url_suffix",
        "tracking_url_template",
        "url_custom_parameters",
    ]
    assert all(column.secondary for column in fields["keywords"].columns[3:])
    assert fields["keywords"].columns[2].default_value == "ENABLED"
    assert fields["keywords"].columns[-1].max_entries == 8
    assert "bid setting, and URL setting" in DEFINITION.presentation.approval_prompt
    assert "optional CPC bid" not in DEFINITION.presentation.approval_prompt


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
        {
            "text": "running shoes",
            "match_type": "EXACT",
            "status": "ENABLED",
            "cpc_bid": "",
            "final_urls": [],
            "final_mobile_urls": [],
            "final_url_suffix": "",
            "tracking_url_template": "",
            "url_custom_parameters": {},
        }
    ]


async def test_positive_keyword_audit_records_exact_default_and_explicit_intent() -> None:
    groups = [ad_group()]
    keywords = [
        GoogleAdsPositiveKeywordEntry(text="running shoes", match_type="EXACT"),
        GoogleAdsPositiveKeywordEntry(
            text="trail shoes",
            match_type="PHRASE",
            status="PAUSED",
            cpc_bid="2.5",
            final_urls=["https://example.com/trail"],
            tracking_url_template="https://track.example.com/{lpurl}",
            url_custom_parameters={"audience": "trail"},
        ),
    ]
    pending = _pending_operation_detail(entry(), groups, keywords)
    assert [intent.fields for intent in pending.intent_groups[0].items] == [
        {"text": "running shoes", "match_type": "EXACT", "status": "ENABLED"},
        {
            "text": "trail shoes",
            "match_type": "PHRASE",
            "status": "PAUSED",
            "cpc_bid": "2.5",
            "final_urls": ["https://example.com/trail"],
            "tracking_url_template": "https://track.example.com/{lpurl}",
            "url_custom_parameters": {"audience": "trail"},
        },
    ]
    creates = [
        GoogleAdsPositiveKeywordCreate("20", "running shoes", "EXACT"),
        GoogleAdsPositiveKeywordCreate(
            "20",
            "trail shoes",
            "PHRASE",
            2_500_000,
            status="PAUSED",
            final_urls=("https://example.com/trail",),
            tracking_url_template="https://track.example.com/{lpurl}",
            url_custom_parameters=(("audience", "trail"),),
        ),
    ]
    ledger = await create_positive_keywords(
        SequencedClient(
            [
                {
                    "results": [
                        {"resourceName": "customers/333/adGroupCriteria/20~91"},
                        {"resourceName": "customers/333/adGroupCriteria/20~92"},
                    ]
                }
            ]
        ),
        customer_id="333",
        login_customer_id="111",
        creates=creates,
        existing_rows=[],
    )
    terminal = terminal_operation_detail(
        pending, ledger, identity_keys=("ad_group_id", "text", "match_type")
    )
    assert [outcome.status for outcome in terminal.outcome_groups[0].outcomes] == [
        "applied",
        "applied",
    ]
    assert all(outcome.effects[0].fields == {} for outcome in terminal.outcome_groups[0].outcomes)


async def test_maximum_positive_keyword_terminal_evidence_stays_bounded() -> None:
    selected = entry()
    groups = [
        GoogleAdsAdGroupReference(
            customer_id="333",
            campaign_id=str(index + 1),
            ad_group_id=str(index + 1),
            label="Ad group",
            scope_label="Campaign",
        )
        for index in range(50)
    ]
    keywords = [
        GoogleAdsPositiveKeywordEntry(
            text=f"keyword{index:03d}",
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
    ledger = await create_positive_keywords(
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
        "integrations.google_ads.tools.create_positive_keywords.run_context_targets", targeting
    )
    duplicate = GoogleAdsPositiveKeywordEntry(text="running shoes", match_type="EXACT")
    with pytest.raises(ModelRetry, match="can appear only once"):
        await google_ads_create_keywords(None, [ad_group()], [duplicate, duplicate])  # type: ignore[arg-type]
    with pytest.raises(ModelRetry, match="can appear only once"):
        await google_ads_create_keywords(  # type: ignore[arg-type]
            None,
            [ad_group()],
            [
                GoogleAdsPositiveKeywordEntry(text="Straße", match_type="EXACT"),
                GoogleAdsPositiveKeywordEntry(text="STRASSE", match_type="EXACT"),
            ],
        )
    groups = [ad_group(str(index + 1)) for index in range(50)]
    keywords = [
        GoogleAdsPositiveKeywordEntry(text=f"keyword {index}", match_type="EXACT")
        for index in range(51)
    ]
    with pytest.raises(ModelRetry, match="must not exceed 2,500"):
        await google_ads_create_keywords(None, groups, keywords)  # type: ignore[arg-type]
    large_keywords = [
        GoogleAdsPositiveKeywordEntry(
            text=f"large keyword {index}",
            match_type="EXACT",
            final_urls=[f"https://example.com/{'a' * 2000}"],
            final_mobile_urls=[f"https://m.example.com/{'b' * 2000}"],
        )
        for index in range(2)
    ]
    with pytest.raises(ModelRetry, match="exact approval evidence"):
        await google_ads_create_keywords(None, groups, large_keywords)  # type: ignore[arg-type]
    targeting.assert_not_awaited()


def test_positive_keyword_display_keeps_every_maximum_fanout_row_bounded() -> None:
    rows = [
        {
            "campaign_id": "1",
            "campaign_name": "c" * 80,
            "ad_group_id": str(index + 1),
            "ad_group_name": "a" * 80,
            "requested": {
                "text": "k" * 80,
                "match_type": "BROAD",
                "status": "PAUSED",
                "cpc_bid": "9223372036854.775807",
                "cpc_bid_micros": "9223372036854775807",
                "final_urls": ["https://example.com/final"],
                "final_mobile_urls": ["https://m.example.com/final"],
                "final_url_suffix": "source=ads",
                "tracking_url_template": "https://track.example.com/{lpurl}",
                "url_custom_parameters": [{"key": "audience", "value": "trail"}],
            },
            "previous_state": "absent",
            "outcome": "failed",
            "error_code": "E" * 60,
            "message": "m" * 120,
        }
        for index in range(2_500)
    ]

    result = display_positive_keyword_result(rows, currency_code="GBP")

    assert len(result["samples"]["failed"]) == 2_500
    assert result["samples_truncated"] is False
    assert len(json.dumps(result, separators=(",", ":"))) < MAX_POSITIVE_KEYWORD_DISPLAY_CHARS
    public_envelope = {
        "results": [
            {
                "provider_key": "google_ads",
                "external_id": "333",
                "display_name": "Retail account",
                "status": "success",
                "error_message": None,
                "data": result,
            }
        ]
    }
    assert (
        len(json.dumps(public_envelope, separators=(",", ":")))
        < MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS
    )

    observed = {
        "text": "k" * 80,
        "match_type": "BROAD",
        "status": "ENABLED",
        "cpc_bid": "9223372036854.775807",
        "cpc_bid_micros": "9223372036854775807",
        "final_urls": [f"https://example.com/{'f' * 60}"],
        "final_mobile_urls": [],
        "final_url_suffix": None,
        "tracking_url_template": None,
        "url_custom_parameters": [],
    }
    skipped_rows = [
        {
            "campaign_id": "1",
            "campaign_name": "c" * 80,
            "ad_group_id": str(index + 1),
            "ad_group_name": "a" * 80,
            "requested": {
                "text": f"keyword{index}",
                "match_type": "EXACT",
                "status": "ENABLED",
            },
            "observed": observed,
            "observed_truncated": True,
            "previous_state": "existing",
            "outcome": "skipped_existing",
            "external_ref": f"customers/333/adGroupCriteria/{index + 1}~1",
        }
        for index in range(2_500)
    ]
    skipped_result = display_positive_keyword_result(skipped_rows, currency_code="GBP")
    assert len(skipped_result["samples"]["skipped_existing"]) == 2_500
    assert (
        len(json.dumps(skipped_result, separators=(",", ":"))) < MAX_POSITIVE_KEYWORD_DISPLAY_CHARS
    )
    skipped_public_envelope = {
        "results": [{**public_envelope["results"][0], "data": skipped_result}]
    }
    assert (
        len(json.dumps(skipped_public_envelope, separators=(",", ":")))
        < MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS
    )
