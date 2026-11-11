# apps/api/integrations/google_ads/operations/keyword_research.py

"""Reads keyword ideas, keyword metrics, and ad group placements from Keyword Planner."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import nonnegative_int

# Google returns up to 10,000 ideas a page, in no volume order; this many is enough to rank.
IDEA_PAGE_SIZE = 2_000
MAX_THEMES_PER_KEYWORD = 10
MAX_CLOSE_VARIANTS = 10
# Google's keyword limit is 80; this bounds whatever comes back.
_MAX_TEXT = 200
_MONTHS = (
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)
# Keyword Planner's own default network, so numbers match what the operator sees there.
_NETWORK = "GOOGLE_SEARCH"


@dataclass(frozen=True, slots=True)
class KeywordMetrics:
    text: str
    avg_monthly_searches: int | None
    # LOW, MEDIUM, or HIGH; None when Google has too little data.
    competition: str | None
    low_bid_micros: int | None
    high_bid_micros: int | None
    # Searches per month, oldest first.
    trend: tuple[int, ...]
    themes: tuple[str, ...] = field(default=())
    close_variants: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class AdGroupPlacement:
    ad_group_id: str
    match_type: str | None


def _month_order(volume: Mapping[str, Any]) -> tuple[int, int]:
    month = volume.get("month")
    return (
        nonnegative_int(volume.get("year")) or 0,
        _MONTHS.index(month) if month in _MONTHS else 0,
    )


def _metrics(text: str, metrics: Any, annotations: Any, variants: Any) -> KeywordMetrics:
    metrics = metrics if isinstance(metrics, Mapping) else {}
    volumes = [
        item for item in metrics.get("monthlySearchVolumes") or [] if isinstance(item, Mapping)
    ]
    concepts = annotations.get("concepts") if isinstance(annotations, Mapping) else None
    themes = dict.fromkeys(
        concept["name"][:_MAX_TEXT]
        for concept in concepts or []
        if isinstance(concept, Mapping) and isinstance(concept.get("name"), str) and concept["name"]
    )
    competition = metrics.get("competition")
    return KeywordMetrics(
        text=text[:_MAX_TEXT],
        avg_monthly_searches=nonnegative_int(metrics.get("avgMonthlySearches")),
        competition=competition if competition in ("LOW", "MEDIUM", "HIGH") else None,
        low_bid_micros=nonnegative_int(metrics.get("lowTopOfPageBidMicros")),
        high_bid_micros=nonnegative_int(metrics.get("highTopOfPageBidMicros")),
        trend=tuple(
            nonnegative_int(volume.get("monthlySearches")) or 0
            for volume in sorted(volumes, key=_month_order)
        ),
        themes=tuple(themes)[:MAX_THEMES_PER_KEYWORD],
        close_variants=tuple(
            item[:_MAX_TEXT] for item in variants or [] if isinstance(item, str) and item
        )[:MAX_CLOSE_VARIANTS],
    )


def _targeting(locations: Sequence[str], language: str | None) -> dict[str, Any]:
    return {
        "geoTargetConstants": [f"geoTargetConstants/{key}" for key in locations],
        **({"language": f"languageConstants/{language}"} if language else {}),
        "keywordPlanNetwork": _NETWORK,
    }


async def generate_keyword_ideas(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    seed: Mapping[str, Any],
    locations: Sequence[str],
    language: str | None,
) -> tuple[list[KeywordMetrics], int]:
    """Returns one page of ideas for the seed with their themes, and Google's total idea count.

    `seed` is one of Google's seed objects, such as `{"keywordSeed": {"keywords": [...]}}`.
    """
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}:generateKeywordIdeas",
        operation="generate_keyword_ideas",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            **seed,
            **_targeting(locations, language),
            "keywordAnnotation": ["KEYWORD_CONCEPT"],
            "pageSize": IDEA_PAGE_SIZE,
        },
    )
    payload = payload if isinstance(payload, Mapping) else {}
    ideas = [
        _metrics(
            row["text"],
            row.get("keywordIdeaMetrics"),
            row.get("keywordAnnotations"),
            row.get("closeVariants"),
        )
        for row in payload.get("results") or []
        if isinstance(row, Mapping) and isinstance(row.get("text"), str) and row["text"]
    ]
    return ideas, max(nonnegative_int(payload.get("totalSize")) or 0, len(ideas))


async def keyword_historical_metrics(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    keywords: Sequence[str],
    locations: Sequence[str],
    language: str | None,
) -> list[KeywordMetrics]:
    """Returns metrics for exact keywords; Google merges close variants into one row."""
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}:generateKeywordHistoricalMetrics",
        operation="keyword_historical_metrics",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"keywords": list(keywords), **_targeting(locations, language)},
    )
    rows = payload.get("results") if isinstance(payload, Mapping) else None
    return [
        _metrics(row["text"], row.get("keywordMetrics"), None, row.get("closeVariants"))
        for row in rows or []
        if isinstance(row, Mapping) and isinstance(row.get("text"), str) and row["text"]
    ]


async def ad_group_placements(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    keywords: Sequence[str],
    ad_group_ids: Sequence[str],
) -> tuple[dict[str, AdGroupPlacement], set[str]]:
    """Returns the ad group Google suggests for each keyword, by keyword text ignoring case, and
    the ad groups Google couldn't use."""
    if any(not value.isdigit() for value in ad_group_ids):
        raise ValueError("Google Ads ad group IDs must contain only digits")
    customer = normalize_customer_id(customer_id)
    payload = await client.post(
        f"customers/{customer}:generateAdGroupThemes",
        operation="generate_ad_group_themes",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "keywords": list(keywords),
            "adGroups": [f"customers/{customer}/adGroups/{value}" for value in ad_group_ids],
        },
    )
    payload = payload if isinstance(payload, Mapping) else {}
    placements: dict[str, AdGroupPlacement] = {}
    for row in payload.get("adGroupKeywordSuggestions") or []:
        if not isinstance(row, Mapping) or not isinstance(row.get("keywordText"), str):
            continue
        ad_group_id = str(row.get("suggestedAdGroup") or "").rpartition("/")[2]
        if ad_group_id in ad_group_ids:
            match_type = row.get("suggestedMatchType")
            placements[row["keywordText"].casefold()] = AdGroupPlacement(
                ad_group_id=ad_group_id,
                match_type=match_type if match_type in ("EXACT", "PHRASE", "BROAD") else None,
            )
    unusable = {
        str(row.get("adGroup") or "").rpartition("/")[2]
        for row in payload.get("unusableAdGroups") or []
        if isinstance(row, Mapping)
    }
    return placements, unusable & set(ad_group_ids)
