# apps/api/integrations/google_ads/operations/list_shared_sets.py

"""List enabled Google Ads shared sets of a requested provider type."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import escape_gaql_like_literal, stream_rows

_SHARED_SET_TYPE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")


async def list_shared_sets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    shared_set_type: str,
    shared_set_ids: Sequence[str] = (),
    search: str | None = None,
    limit: int | None,
) -> list[Mapping[str, Any]]:
    normalized_customer_id = normalize_customer_id(customer_id)
    if _SHARED_SET_TYPE_PATTERN.fullmatch(shared_set_type) is None:
        raise ValueError("Google Ads shared set type must be an uppercase provider enum identifier")
    if limit is not None and (limit < 1 or limit > 101):
        raise ValueError("Google Ads shared set lookup limit must be between 1 and 101")
    if any(not shared_set_id.isdigit() for shared_set_id in shared_set_ids):
        raise ValueError("Google Ads shared set ids must contain only digits")
    id_filter = (
        f" AND shared_set.id IN ({', '.join(sorted(set(shared_set_ids)))})"
        if shared_set_ids
        else ""
    )
    name_filter = (
        f" AND shared_set.name LIKE '%{escape_gaql_like_literal(search.strip())}%'"
        if search and search.strip()
        else ""
    )
    limit_clause = f" LIMIT {limit}" if limit is not None else ""
    query = (
        "SELECT shared_set.id, shared_set.name, shared_set.member_count FROM shared_set "  # noqa: S608 -- validated enum/ids and escaped search
        f"WHERE shared_set.type = '{shared_set_type}' AND shared_set.status = 'ENABLED'"
        f"{id_filter}{name_filter} ORDER BY shared_set.name, shared_set.id{limit_clause}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_shared_sets",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [
        shared_set
        for row in stream_rows(payload)
        if isinstance((shared_set := row.get("sharedSet")), Mapping)
    ]
