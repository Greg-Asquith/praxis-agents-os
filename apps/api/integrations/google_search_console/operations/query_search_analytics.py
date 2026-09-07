# apps/api/integrations/google_search_console/operations/query_search_analytics.py

"""Run a bounded Search Analytics query for one site."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleSearchConsoleClient, site_path
from ..tools.schemas import GoogleSearchConsoleSearchAnalyticsInput
from .utils import bounded_text, finite_float, invalid_response, untrusted

_UNTRUSTED_DIMENSIONS = frozenset({"page", "query"})
MAX_SEARCH_ANALYTICS_ROWS = 25_000


async def query_search_analytics(
    client: GoogleSearchConsoleClient,
    *,
    site_url: str,
    request: GoogleSearchConsoleSearchAnalyticsInput,
    max_rows: int,
) -> dict[str, Any]:
    """Returns typed, bounded search-performance rows for one site."""
    requested_rows = min(request.row_limit, max_rows, MAX_SEARCH_ANALYTICS_ROWS)
    body: dict[str, Any] = {
        "startDate": request.start_date,
        "endDate": request.end_date,
        "dimensions": request.dimensions,
        "type": request.search_type,
        "aggregationType": request.aggregation_type,
        "rowLimit": requested_rows,
        "startRow": request.start_row,
        "dataState": request.data_state,
    }
    if request.filters:
        body["dimensionFilterGroups"] = [
            {
                "groupType": "and",
                "filters": [
                    {
                        "dimension": item.dimension,
                        "operator": item.operator,
                        "expression": item.expression,
                    }
                    for item in request.filters
                ],
            }
        ]

    payload = await client.webmasters_post(
        f"{site_path(site_url)}/searchAnalytics/query",
        operation="query_search_analytics",
        policy=IntegrationRequestPolicy.READ,
        json=body,
    )
    if not isinstance(payload, dict):
        raise invalid_response("query_search_analytics")
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_rows, list):
        raise invalid_response("query_search_analytics")

    rows = [
        _shape_row(item, dimensions=request.dimensions, site_url=site_url)
        for item in raw_rows[:requested_rows]
    ]
    truncated = len(raw_rows) >= requested_rows
    return {
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "truncation_note": (
            "The result may contain more rows. Page with start_row or add filters."
            if truncated
            else None
        ),
        "response_aggregation_type": bounded_text(payload.get("responseAggregationType")),
        "start_date": request.start_date,
        "end_date": request.end_date,
        "search_type": request.search_type,
    }


def _shape_row(
    value: Any,
    *,
    dimensions: list[str],
    site_url: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_response("query_search_analytics")
    raw_keys = value.get("keys", [])
    if not isinstance(raw_keys, list) or len(raw_keys) != len(dimensions):
        raise invalid_response("query_search_analytics")
    keys: dict[str, Any] = {}
    for dimension, raw_value in zip(dimensions, raw_keys, strict=True):
        text = bounded_text(raw_value, max_length=4_096)
        keys[dimension] = (
            untrusted(
                text,
                source_kind="search_console_row",
                source_ref=site_url,
            )
            if dimension in _UNTRUSTED_DIMENSIONS
            else text
        )
    clicks = finite_float(value.get("clicks"), operation="query_search_analytics")
    impressions = finite_float(value.get("impressions"), operation="query_search_analytics")
    ctr = finite_float(value.get("ctr"), operation="query_search_analytics")
    position = finite_float(value.get("position"), operation="query_search_analytics")
    if clicks < 0 or impressions < 0 or not 0 <= ctr <= 1 or position < 0:
        raise invalid_response("query_search_analytics")
    return {
        "keys": keys,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }
