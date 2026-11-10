# apps/api/integrations/google_ads/operations/list_positive_keywords.py

"""List Google Ads positive keywords for lookup and live verification."""

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
    exclude_removed: bool = True,
) -> list[Mapping[str, Any]]:
    """Returns bounded positive keywords in provider order.

    `exclude_removed` (on by default) leaves out removed keywords and those under a removed ad
    group or campaign, which Google won't change.
    """
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
    ]
    if exclude_removed:
        filters.extend(
            (
                "ad_group_criterion.status != 'REMOVED'",
                "ad_group.status != 'REMOVED'",
                "campaign.status != 'REMOVED'",
            )
        )
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


def _escape_re2_literal(value: str) -> str:
    return "".join(
        f"\\{character}" if character in r"\.^$|?*+()[]{}" else character for character in value
    )
