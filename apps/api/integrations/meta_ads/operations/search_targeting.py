# apps/api/integrations/meta_ads/operations/search_targeting.py

"""Find Meta targeting options by name and return the keys a targeting draft takes."""

import json
from typing import Any

from pydantic import ValidationError

from services.integrations.http import IntegrationRequestPolicy

from ..client import MetaAdsClient
from ..throttle import ensure_account_available
from ..tools.schemas.targeting import (
    MetaAdsAudienceSize,
    MetaAdsTargetingKind,
    MetaAdsTargetingOption,
    MetaAdsTargetingSearchData,
)
from .targeting import DEMOGRAPHIC_CATEGORIES
from .values import invalid_response, squashed_text

_OPERATION = "search_targeting"
_GEO_TYPES = {"country": "country", "region": "region", "city": "city", "postcode": "zip"}
# Behaviours and demographics are listed whole by class and matched by name here.
_CATEGORY_CLASSES = {"behavior": "behaviors", "demographic": "demographics"}
_CATEGORY_LIST_LIMIT = 1000
_MAX_ROWS = 1000


async def search_targeting(
    client: MetaAdsClient,
    *,
    account_id: str,
    kind: MetaAdsTargetingKind,
    query: str,
    country_code: str | None,
    limit: int,
    max_response_bytes: int | None = None,
) -> MetaAdsTargetingSearchData:
    ensure_account_available(account_id, operation=_OPERATION)
    payload = await client.graph_get(
        "search",
        params=_params(kind, query, country_code, limit),
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        max_response_bytes=max_response_bytes,
        usage_account_id=account_id,
    )
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        raise invalid_response(
            "Meta Ads returned an invalid targeting search.", operation=_OPERATION
        )
    needle = query.strip().casefold()
    options = [
        option
        for row in rows
        if (option := _option(kind, row)) is not None
        and (kind not in _CATEGORY_CLASSES or needle in option.name.casefold())
    ]
    return MetaAdsTargetingSearchData(options=options[:limit], truncated=len(options) > limit)


def _params(
    kind: MetaAdsTargetingKind, query: str, country_code: str | None, limit: int
) -> dict[str, Any]:
    if kind in _CATEGORY_CLASSES:
        return {
            "type": "adTargetingCategory",
            "class": _CATEGORY_CLASSES[kind],
            "limit": _CATEGORY_LIST_LIMIT,
        }
    # One extra row shows whether Meta has more.
    params: dict[str, Any] = {"q": query.strip(), "limit": limit + 1}
    if kind == "interest":
        params["type"] = "adinterest"
    elif kind == "language":
        params["type"] = "adlocale"
    else:
        params["type"] = "adgeolocation"
        params["location_types"] = json.dumps([_GEO_TYPES[kind]])
        if country_code:
            params["country_code"] = country_code
    return params


def _option(kind: MetaAdsTargetingKind, row: Any) -> MetaAdsTargetingOption | None:
    """Builds an option from a row, skipping rows a targeting draft couldn't use."""
    if not isinstance(row, dict):
        raise invalid_response(
            "Meta Ads returned an invalid targeting option.", operation=_OPERATION
        )
    if kind in _GEO_TYPES and row.get("type") != _GEO_TYPES[kind]:
        return None
    category = row.get("type") if kind == "demographic" else None
    if kind == "demographic" and category not in DEMOGRAPHIC_CATEGORIES:
        return None
    value = row.get("key") if kind in _GEO_TYPES or kind == "language" else row.get("id")
    key = str(value) if isinstance(value, int | str) and not isinstance(value, bool) else ""
    try:
        return MetaAdsTargetingOption(
            kind=kind,
            key=key,
            name=squashed_text(row.get("name"), 512) or key,
            description=_description(kind, row),
            audience_size_range=_size(row),
            country_code=row.get("country_code") if kind in _GEO_TYPES else None,
            region=row.get("region") if kind in ("city", "postcode") else None,
            category=category,
        )
    except ValidationError:
        raise invalid_response(
            "Meta Ads returned an invalid targeting option.", operation=_OPERATION
        ) from None


def _description(kind: MetaAdsTargetingKind, row: dict[str, Any]) -> str | None:
    if kind in _GEO_TYPES:
        value = row.get("country_name")
    elif isinstance(row.get("path"), list) and len(row["path"]) > 1:
        # Meta's path ends with the option itself, so the rest names where it sits.
        value = " > ".join(str(part) for part in row["path"][:-1])
    else:
        value = row.get("description")
    return squashed_text(value, 512)


def _size(row: dict[str, Any]) -> MetaAdsAudienceSize | None:
    lower = row.get("audience_size_lower_bound")
    upper = row.get("audience_size_upper_bound")
    valid = all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (lower, upper)
    )
    return MetaAdsAudienceSize(lower=lower, upper=upper) if valid else None
