# apps/api/integrations/google_ads/operations/run_report.py

"""Read every returned GAQL row for one Google Ads customer."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient
from .utils import stream_rows


async def run_report(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    currency_code: str,
    login_customer_id: str,
    query: str,
    max_response_bytes: int,
) -> dict[str, Any]:
    payload = await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation="run_report",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
        max_response_bytes=max_response_bytes,
    )
    rows = stream_rows(payload)
    return {
        "currency_code": currency_code,
        "rows": rows,
        "row_count": len(rows),
        "truncated": False,
        "truncation_note": None,
    }
