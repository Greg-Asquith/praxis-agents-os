# apps/api/integrations/google_ads/operations/read_search_terms.py

"""Reads search term figures for a date range, and the keywords ad groups already bid on."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import nonnegative_int, stream_rows

# Only stops an unbounded read; a busy ad group has thousands of terms a week.
_MAX_ROWS = 100_000
_TOO_MANY = (
    "These ad groups had too many search terms to check at once. Choose fewer ad groups or a "
    "shorter date range."
)


@dataclass(frozen=True, slots=True)
class SearchTermStats:
    """One search term's figures in one ad group over the date range."""

    status: str
    clicks: int
    impressions: int
    cost_micros: int
    conversions: float


def keyword_key(ad_group: str, text: str, match_type: str) -> str:
    """Names one keyword bid on in an ad group; Google ignores case."""
    return f"{ad_group}/keyword/{match_type}/{' '.join(text.casefold().split())}"


def search_term_key(ad_group: str, term: str) -> str:
    """Names a search term in the ad group it matched in; Google ignores case."""
    return f"{ad_group}/term/{' '.join(term.casefold().split())}"


async def read_search_terms(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: Sequence[str],
    start_date: date,
    end_date: date,
) -> dict[str, SearchTermStats]:
    """Returns each search term's figures by `search_term_key`, in one query.

    Raises:
        IntegrationValidationError: When the ad groups hold too many terms to read.
    """
    if not ad_group_ids:
        return {}
    if any(not value.isdigit() for value in ad_group_ids):
        raise ValueError("Google Ads ids must contain only digits")
    customer = normalize_customer_id(customer_id)
    rows = await _rows(
        client,
        customer,
        login_customer_id,
        "SELECT search_term_view.search_term, search_term_view.status, ad_group.id, "  # noqa: S608 -- ISO dates and digit-only ids
        "metrics.clicks, metrics.impressions, metrics.cost_micros, metrics.conversions "
        f"FROM search_term_view WHERE segments.date BETWEEN '{start_date.isoformat()}' "
        f"AND '{end_date.isoformat()}' AND ad_group.id IN ({', '.join(sorted(set(ad_group_ids)))})",
        "read_search_terms",
    )
    terms: dict[str, SearchTermStats] = {}
    for row in rows:
        view = row.get("searchTermView") or {}
        term = view.get("searchTerm")
        if not isinstance(term, str) or not term:
            continue
        metrics = row.get("metrics") or {}
        stats = SearchTermStats(
            status=str(view.get("status") or "UNKNOWN"),
            clicks=nonnegative_int(metrics.get("clicks")) or 0,
            impressions=nonnegative_int(metrics.get("impressions")) or 0,
            cost_micros=nonnegative_int(metrics.get("costMicros")) or 0,
            conversions=float(metrics.get("conversions") or 0),
        )
        ad_group = f"customers/{customer}/adGroups/{(row.get('adGroup') or {}).get('id')}"
        key = search_term_key(ad_group, term)
        # Google can split one term over rows, such as by the keyword it matched.
        if earlier := terms.get(key):
            stats = replace(
                stats,
                clicks=earlier.clicks + stats.clicks,
                impressions=earlier.impressions + stats.impressions,
                cost_micros=earlier.cost_micros + stats.cost_micros,
                conversions=earlier.conversions + stats.conversions,
            )
        terms[key] = stats
    return terms


async def read_ad_group_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: Sequence[str],
) -> dict[str, str]:
    """Returns the resource name of each keyword the ad groups bid on, by `keyword_key`."""
    if not ad_group_ids:
        return {}
    if any(not value.isdigit() for value in ad_group_ids):
        raise ValueError("Google Ads ids must contain only digits")
    customer = normalize_customer_id(customer_id)
    rows = await _rows(
        client,
        customer,
        login_customer_id,
        "SELECT ad_group.id, ad_group_criterion.resource_name, ad_group_criterion.keyword.text, "  # noqa: S608 -- digit-only ids
        "ad_group_criterion.keyword.match_type FROM ad_group_criterion "
        "WHERE ad_group_criterion.type = 'KEYWORD' AND ad_group_criterion.negative = FALSE "
        "AND ad_group_criterion.status != 'REMOVED' "
        f"AND ad_group.id IN ({', '.join(sorted(set(ad_group_ids)))})",
        "read_search_term_keywords",
    )
    keywords: dict[str, str] = {}
    for row in rows:
        criterion = row.get("adGroupCriterion") or {}
        keyword = criterion.get("keyword") or {}
        name, text, match_type = (
            criterion.get("resourceName"),
            keyword.get("text"),
            keyword.get("matchType"),
        )
        if isinstance(name, str) and isinstance(text, str) and isinstance(match_type, str):
            ad_group = f"customers/{customer}/adGroups/{(row.get('adGroup') or {}).get('id')}"
            keywords[keyword_key(ad_group, text, match_type)] = name
    return keywords


async def _rows(
    client: GoogleAdsClient, customer: str, login_customer_id: str, query: str, operation: str
) -> list[dict[str, Any]]:
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation=operation,
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    rows = stream_rows(payload, max_rows=_MAX_ROWS)
    if len(rows) >= _MAX_ROWS:
        raise IntegrationValidationError(
            _TOO_MANY,
            provider_key="google_ads",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        )
    return rows
