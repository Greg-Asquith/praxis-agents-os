# apps/api/integrations/google_ads/operations/list_positive_keywords.py

"""List Google Ads positive keywords for lookup and live verification."""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import (
    entity_id_boundary_filter,
    escape_gaql_like_literal,
    escape_gaql_string_literal,
    stream_rows,
)


async def list_positive_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    criterion_ids: Sequence[str] = (),
    ad_group_ids: Sequence[str] = (),
    keyword_texts: Sequence[str] = (),
    keyword_match_types: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_ad_group_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Returns bounded, non-removed positive keyword criteria in provider order."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > 2501:
        raise ValueError("Google Ads positive-keyword lookup limit must be between 1 and 2,501")
    if any(not value.isdigit() for value in (*criterion_ids, *ad_group_ids)):
        raise ValueError("Google Ads positive-keyword ids must contain only digits")
    normalized_criterion_ids = sorted(set(criterion_ids))
    normalized_ad_group_ids = sorted(set(ad_group_ids))
    normalized_keyword_texts = list(dict.fromkeys(keyword_texts))
    normalized_match_types = sorted(set(keyword_match_types))
    if len(normalized_criterion_ids) > 50 or len(normalized_ad_group_ids) > 50:
        raise ValueError("Google Ads positive-keyword lookup accepts at most 50 ids")
    if len(normalized_keyword_texts) > 500 or any(
        not text or len(text) > 80 for text in normalized_keyword_texts
    ):
        raise ValueError("Google Ads positive-keyword lookup accepts at most 500 keyword texts")
    if any(value not in {"EXACT", "PHRASE", "BROAD"} for value in normalized_match_types):
        raise ValueError("Google Ads positive-keyword lookup match types are invalid")

    filters = [
        "ad_group_criterion.type = 'KEYWORD'",
        "ad_group_criterion.negative = FALSE",
        "ad_group_criterion.status != 'REMOVED'",
    ]
    if normalized_criterion_ids:
        filters.append(
            f"ad_group_criterion.criterion_id IN ({', '.join(normalized_criterion_ids)})"
        )
    if normalized_ad_group_ids:
        filters.append(f"ad_group.id IN ({', '.join(normalized_ad_group_ids)})")
    if normalized_keyword_texts:
        alternatives = "|".join(_escape_re2_literal(text) for text in normalized_keyword_texts)
        pattern = escape_gaql_string_literal(
            f"(?i)^(?:{alternatives})$",
            max_length=50_000,
        )
        filters.append(f"ad_group_criterion.keyword.text REGEXP_MATCH '{pattern}'")
    if normalized_match_types:
        values = ", ".join(f"'{value}'" for value in normalized_match_types)
        filters.append(f"ad_group_criterion.keyword.match_type IN ({values})")
    if search and search.strip():
        filters.append(
            f"ad_group_criterion.keyword.text LIKE '%{escape_gaql_like_literal(search.strip())}%'"
        )
    if minimum_ad_group_id is None:
        boundary_filter = entity_id_boundary_filter(
            "ad_group_criterion.criterion_id",
            minimum_id=minimum_id,
            inclusive=minimum_id_inclusive,
        )
    else:
        if minimum_id is None:
            raise ValueError("Google Ads keyword cursor requires a criterion id")
        criterion_after = entity_id_boundary_filter(
            "ad_group_criterion.criterion_id",
            minimum_id=minimum_id,
            inclusive=False,
        )
        ad_group_after = entity_id_boundary_filter(
            "ad_group.id",
            minimum_id=minimum_ad_group_id,
            inclusive=minimum_id_inclusive,
        )
        boundary_filter = (
            f"({criterion_after} OR (ad_group_criterion.criterion_id = {minimum_id} "
            f"AND {ad_group_after}))"
        )
    if boundary_filter:
        filters.append(boundary_filter)
    query = (
        "SELECT campaign.id, campaign.name, ad_group.id, ad_group.name, "  # noqa: S608 -- digit-only ids and escaped search
        "ad_group.status, ad_group_criterion.resource_name, "
        "ad_group_criterion.criterion_id, ad_group_criterion.status, "
        "ad_group_criterion.negative, ad_group_criterion.type, "
        "ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, "
        "ad_group_criterion.bid_modifier, ad_group_criterion.cpc_bid_micros, "
        "ad_group_criterion.final_urls, "
        "ad_group_criterion.final_mobile_urls, ad_group_criterion.final_url_suffix, "
        "ad_group_criterion.tracking_url_template, ad_group_criterion.url_custom_parameters "
        "FROM ad_group_criterion "
        f"WHERE {' AND '.join(filters)} "
        f"ORDER BY ad_group_criterion.criterion_id, ad_group.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_positive_keywords",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [row for row in stream_rows(payload, max_rows=limit) if isinstance(row, Mapping)]


async def list_positive_keyword_pairs(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    keyword_targets: Sequence[tuple[str, str, str]],
) -> list[Mapping[str, Any]]:
    """Return only requested case-insensitive keyword and match-type pairs."""
    unique_targets: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for ad_group_id, text, match_type in keyword_targets:
        key = (ad_group_id, " ".join(text.split()).casefold(), match_type)
        unique_targets.setdefault(key, (ad_group_id, text, match_type))
    if not unique_targets:
        return []
    texts_by_scope: dict[tuple[str, str], set[str]] = {}
    for ad_group_id, text, match_type in unique_targets.values():
        texts_by_scope.setdefault((match_type, ad_group_id), set()).add(text)
    grouped: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for (match_type, ad_group_id), texts in texts_by_scope.items():
        text_group = tuple(sorted(texts, key=lambda value: (value.casefold(), value)))
        grouped.setdefault((match_type, text_group), []).append(ad_group_id)

    rows_by_match_type = await asyncio.gather(
        *(
            list_positive_keywords(
                client,
                customer_id=customer_id,
                login_customer_id=login_customer_id,
                ad_group_ids=ad_group_ids,
                keyword_texts=texts,
                keyword_match_types=[match_type],
                limit=len(ad_group_ids) * len(texts) + 1,
            )
            for (match_type, texts), ad_group_ids in grouped.items()
        )
    )
    rows = [row for match_rows in rows_by_match_type for row in match_rows]
    expected_maximum = len(unique_targets)
    if len(rows) > expected_maximum:
        raise ValueError("Google Ads returned contradictory positive keyword lookup results")
    return rows


def _escape_re2_literal(value: str) -> str:
    return "".join(
        f"\\{character}" if character in r"\.^$|?*+()[]{}" else character for character in value
    )
