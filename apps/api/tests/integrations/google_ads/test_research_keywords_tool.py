# apps/api/tests/integrations/google_ads/test_research_keywords_tool.py

"""Keyword research: what goes to Keyword Planner, how rows are ranked, and which account runs."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry

from integrations.google_ads.references import GoogleAdsAdGroupReference
from integrations.google_ads.tools import research_keywords as tool_module
from integrations.google_ads.tools.schemas.keyword_research import GoogleAdsKeywordResearchOutput
from services.integrations.context.domain import ResolvedActiveContext
from tests.integrations.google_ads.support import _writable_google_ads_entry


def _entry(external_id: str = "111"):
    return replace(
        _writable_google_ads_entry(),
        external_id=external_id,
        permissions_metadata={
            "login_customer_id": "999",
            "currency_code": "GBP",
            "time_zone": "Europe/London",
        },
    )


def _metrics(searches: int, low: str = "580000", months: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "avgMonthlySearches": str(searches),
        "competition": "HIGH",
        "lowTopOfPageBidMicros": low,
        "highTopOfPageBidMicros": "1420000",
        "monthlySearchVolumes": [
            {"year": "2026", "month": month, "monthlySearches": str(index * 100)}
            for index, month in enumerate(months, start=1)
        ],
    }


class _PlannerClient:
    def __init__(self, *, total: int = 3) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.total = total

    async def post(self, path: str, **kwargs):
        body = kwargs["json"]
        self.calls.append((path, body))
        assert kwargs["login_customer_id"] == "999"
        if path.endswith(":generateKeywordIdeas"):
            return {
                "results": [
                    {"text": "trail running shoes", "keywordIdeaMetrics": _metrics(22_200)},
                    {
                        "text": "running shoes",
                        "keywordIdeaMetrics": _metrics(90_500),
                        "keywordAnnotations": {"concepts": [{"name": "Running"}]},
                    },
                    {
                        "text": "waterproof trail shoes",
                        # Google lists months in no guaranteed order.
                        "keywordIdeaMetrics": _metrics(6_600, months=("MARCH", "JANUARY")),
                        "keywordAnnotations": {
                            "concepts": [
                                {"name": "Trail", "conceptGroup": {"type": "NON_BRAND"}},
                                {"name": "Waterproof"},
                            ]
                        },
                    },
                ],
                "totalSize": str(self.total),
            }
        if path.endswith(":generateKeywordHistoricalMetrics"):
            return {
                "results": [
                    {
                        "text": "fell running shoes",
                        "closeVariants": ["fell running shoe"],
                        "keywordMetrics": _metrics(1_300, low="390000"),
                    }
                ]
            }
        if path.endswith(":generateAdGroupThemes"):
            return {
                "adGroupKeywordSuggestions": [
                    {
                        "keywordText": "trail running shoes",
                        "suggestedMatchType": "PHRASE",
                        "suggestedAdGroup": "customers/111/adGroups/20",
                    },
                    # A suggestion outside the ad groups asked for is ignored.
                    {
                        "keywordText": "running shoes",
                        "suggestedMatchType": "BROAD",
                        "suggestedAdGroup": "customers/111/adGroups/99",
                    },
                ],
                "unusableAdGroups": [{"adGroup": "customers/111/adGroups/21"}],
            }
        query = body["query"]
        if "geo_target_constant" in query:
            return [{"results": [{"geoTargetConstant": {"id": "2826", "name": "United Kingdom"}}]}]
        return [{"results": [{"languageConstant": {"id": "1000", "name": "English"}}]}]


def _ctx(*entries):
    return SimpleNamespace(
        deps=SimpleNamespace(
            active_context=ResolvedActiveContext(entries=entries),
            workspace=SimpleNamespace(id=uuid4()),
            agent=SimpleNamespace(id=uuid4()),
            run=SimpleNamespace(id=uuid4()),
        ),
        tool_name="google_ads_research_keywords",
        tool_call_id="research-call",
    )


@pytest.fixture
def client(monkeypatch) -> _PlannerClient:
    planner = _PlannerClient()
    monkeypatch.setattr(tool_module, "google_ads_client", AsyncMock(return_value=planner))
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event",
        AsyncMock(return_value=uuid4()),
    )
    return planner


def _ad_group(ad_group_id: str, customer_id: str = "111") -> GoogleAdsAdGroupReference:
    return GoogleAdsAdGroupReference(
        customer_id=customer_id,
        campaign_id="10",
        ad_group_id=ad_group_id,
        label=f"Trail {ad_group_id}",
    )


async def test_ideas_and_exact_keywords_rank_by_searches_with_requested_rows_kept(client) -> None:
    result = await tool_module.google_ads_research_keywords(
        _ctx(_entry()),
        seeds=["running shoes"],
        url="https://shop.example.com/trail",
        keywords=["fell running shoes"],
        locations=["2826"],
        language="1000",
        limit=3,
    )

    paths = [path for path, _body in client.calls]
    assert paths[-2:] == [
        "customers/111:generateKeywordHistoricalMetrics",
        "customers/111:generateKeywordIdeas",
    ]
    ideas_body = client.calls[-1][1]
    assert ideas_body == {
        "keywordAndUrlSeed": {
            "url": "https://shop.example.com/trail",
            "keywords": ["running shoes"],
        },
        "geoTargetConstants": ["geoTargetConstants/2826"],
        "language": "languageConstants/1000",
        "keywordPlanNetwork": "GOOGLE_SEARCH",
        "keywordAnnotation": ["KEYWORD_CONCEPT"],
        "pageSize": 2_000,
    }
    data = GoogleAdsKeywordResearchOutput.model_validate(result).results[0].data
    assert [(idea.text, idea.requested) for idea in data.ideas] == [
        ("running shoes", False),
        ("trail running shoes", False),
        ("fell running shoes", True),
    ]
    assert (data.ideas[2].low_bid, data.ideas[2].high_bid) == ("0.39", "1.42")
    assert data.truncated is True
    assert [place.name for place in data.locations] == ["United Kingdom"]
    assert data.language is not None and data.language.name == "English"


async def test_a_home_page_researches_the_whole_site_and_months_come_oldest_first(client) -> None:
    result = await tool_module.google_ads_research_keywords(
        _ctx(_entry()), url="https://shop.example.com/"
    )

    assert client.calls[-1][1]["siteSeed"] == {"site": "shop.example.com"}
    assert "geoTargetConstants" in client.calls[-1][1]
    ideas = GoogleAdsKeywordResearchOutput.model_validate(result).results[0].data.ideas
    waterproof = next(idea for idea in ideas if idea.text == "waterproof trail shoes")
    assert waterproof.trend == [200, 100]
    assert waterproof.themes == ["Trail", "Waterproof"]


async def test_a_url_with_no_site_is_refused_before_any_request(client) -> None:
    with pytest.raises(ModelRetry):
        await tool_module.google_ads_research_keywords(_ctx(_entry()), url="https://?q=shoes")

    assert client.calls == []


async def test_ad_groups_get_googles_placements_and_unusable_ones_are_flagged(client) -> None:
    result = await tool_module.google_ads_research_keywords(
        _ctx(_entry()), seeds=["trail shoes"], ad_groups=[_ad_group("20"), _ad_group("21")]
    )

    assert client.calls[-1] == (
        "customers/111:generateAdGroupThemes",
        {
            "keywords": ["running shoes", "trail running shoes", "waterproof trail shoes"],
            "adGroups": ["customers/111/adGroups/20", "customers/111/adGroups/21"],
        },
    )
    data = GoogleAdsKeywordResearchOutput.model_validate(result).results[0].data
    placed = {idea.text: (idea.ad_group_id, idea.match_type) for idea in data.ideas}
    assert placed["trail running shoes"] == ("20", "PHRASE")
    assert placed["running shoes"] == (None, None)
    assert [(group.ad_group_id, group.usable) for group in data.ad_groups] == [
        ("20", True),
        ("21", False),
    ]


async def test_ad_groups_from_an_account_outside_the_context_are_refused(client) -> None:
    with pytest.raises(ModelRetry):
        await tool_module.google_ads_research_keywords(
            _ctx(_entry()), seeds=["trail shoes"], ad_groups=[_ad_group("20", customer_id="222")]
        )

    assert client.calls == []


async def test_ad_groups_choose_their_account_when_several_are_selected(client) -> None:
    result = await tool_module.google_ads_research_keywords(
        _ctx(_entry(), _entry("333")),
        seeds=["trail shoes"],
        ad_groups=[_ad_group("20", customer_id="333")],
    )

    assert {path.split(":")[0] for path, _body in client.calls} == {"customers/333"}
    assert GoogleAdsKeywordResearchOutput.model_validate(result).results[0].data.account_id == "333"


async def test_an_unknown_location_key_is_refused_before_any_planner_call(client) -> None:
    result = await tool_module.google_ads_research_keywords(
        _ctx(_entry()), seeds=["trail shoes"], locations=["9999"]
    )

    entry = GoogleAdsKeywordResearchOutput.model_validate(result).results[0]
    assert entry.status == "error"
    assert "Unknown location keys: 9999" in (entry.error_message or "")
    assert not any(":generate" in path for path, _body in client.calls)
