# apps/api/integrations/google_ads/operations/run_report.py

"""Run a bounded GAQL report for one Google Ads customer."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient
from .utils import bounded_query, stream_rows


async def run_report(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    currency_code: str,
    login_customer_id: str,
    query: str,
    max_rows: int,
) -> dict[str, Any]:
    query_with_limit = bounded_query(query, max_rows=max_rows)
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation="run_report",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query_with_limit},
    )
    rows = stream_rows(payload, max_rows=max_rows + 1)
    truncated = len(rows) > max_rows
    bounded = rows[:max_rows]
    return {
        "currency_code": currency_code,
        "rows": bounded,
        "row_count": len(bounded),
        "truncated": truncated,
        "truncation_note": (
            f"Report limited to {max_rows} rows. Narrow the GAQL query to retrieve more."
            if truncated
            else None
        ),
    }
