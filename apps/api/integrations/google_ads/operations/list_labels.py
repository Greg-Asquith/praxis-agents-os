# apps/api/integrations/google_ads/operations/list_labels.py

"""List enabled Google Ads labels owned by one customer."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows


async def list_labels(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    label_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Returns enabled labels whose resource belongs to the requested customer."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > 101:
        raise ValueError("Google Ads label lookup limit must be between 1 and 101")
    if any(not label_id.isdigit() for label_id in label_ids):
        raise ValueError("Google Ads label ids must contain only digits")
    id_filter = f" AND label.id IN ({', '.join(sorted(set(label_ids)))})" if label_ids else ""
    name_filter = (
        f" AND label.name LIKE '%{escape_gaql_like_literal(search.strip())}%'"
        if search and search.strip()
        else ""
    )
    boundary_filter = entity_id_boundary_filter(
        "label.id",
        minimum_id=minimum_id,
        inclusive=minimum_id_inclusive,
    )
    boundary_clause = f" AND {boundary_filter}" if boundary_filter else ""
    query = (
        "SELECT label.resource_name, label.id, label.name, label.status, "  # noqa: S608 -- digit-only ids and escaped search
        "label.text_label.description, label.text_label.background_color FROM label "
        f"WHERE label.status = 'ENABLED'{id_filter}{name_filter}{boundary_clause} "
        f"ORDER BY label.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_labels",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    owned_prefix = f"customers/{normalized_customer_id}/labels/"
    return [
        label
        for row in stream_rows(payload, max_rows=limit)
        if isinstance((label := row.get("label")), Mapping)
        and str(label.get("resourceName", "")).startswith(owned_prefix)
    ]
