# apps/api/integrations/google_ads/operations/run_report.py

"""Run a bounded GAQL report for one Google Ads customer."""

from typing import Any

from services.agents.runtime.untrusted import UntrustedContent

from ..client import GoogleAdsClient
from .utils import bounded_query, stream_rows


async def run_report(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    query: str,
    max_rows: int,
) -> dict[str, Any]:
    query_with_limit = bounded_query(query, max_rows=max_rows)
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation="run_report",
        login_customer_id=login_customer_id,
        json={"query": query_with_limit},
    )
    rows = stream_rows(payload)
    truncated = len(rows) > max_rows
    bounded = [_untrusted_row(row, customer_id=customer_id) for row in rows[:max_rows]]
    return {
        "rows": bounded,
        "row_count": len(bounded),
        "truncated": truncated,
        "truncation_note": (
            f"Report limited to {max_rows} rows. Narrow the GAQL query to retrieve more."
            if truncated
            else None
        ),
    }


def _untrusted_row(value: Any, *, customer_id: str) -> Any:
    if isinstance(value, str):
        return UntrustedContent(
            source_kind="google_ads_report",
            source_ref=customer_id,
            content=value,
        )
    if isinstance(value, dict):
        return {key: _untrusted_row(item, customer_id=customer_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_untrusted_row(item, customer_id=customer_id) for item in value]
    return value
