# apps/api/integrations/google_ads/operations/get_account.py

"""Read one Google Ads account's settings and this month's cost."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient
from .utils import nonnegative_int, stream_rows

_OPERATION = "get_account"
_ACCOUNT_QUERY = """
SELECT
  customer.id,
  customer.descriptive_name,
  customer.status,
  customer.currency_code,
  customer.time_zone,
  customer.manager,
  customer.auto_tagging_enabled
FROM customer
""".strip()
# Google reports dates in the account's time zone; THIS_MONTH includes today.
_COST_QUERY = """
SELECT segments.date, metrics.cost_micros
FROM customer
WHERE segments.date DURING THIS_MONTH
""".strip()


async def get_account(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    max_response_bytes: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    rows = stream_rows(
        await _search(client, customer_id, login_customer_id, _ACCOUNT_QUERY, max_response_bytes)
    )
    customer = rows[0].get("customer") if rows else None
    if not isinstance(customer, dict):
        raise IntegrationValidationError(
            "Google Ads didn't return this account's settings.",
            provider_key="google_ads",
            operation=_OPERATION,
        )
    currency = str(customer.get("currencyCode") or "")
    time_zone = str(customer.get("timeZone") or "")
    manager = bool(customer.get("manager", False))
    cost_today = cost_this_month = None
    if not manager:
        cost_rows = stream_rows(
            await _search(client, customer_id, login_customer_id, _COST_QUERY, max_response_bytes)
        )
        cost_today, cost_this_month = _costs(cost_rows, _account_today(time_zone, now))
    auto_tagging = customer.get("autoTaggingEnabled")
    return {
        "customer_id": customer_id,
        "name": str(customer.get("descriptiveName") or "").strip() or None,
        "status": str(customer.get("status") or "UNKNOWN"),
        "currency": currency,
        "time_zone": time_zone,
        "manager": manager,
        "auto_tagging_enabled": auto_tagging if isinstance(auto_tagging, bool) else None,
        "cost_today": cost_today,
        "cost_this_month": cost_this_month,
    }


async def _search(
    client: GoogleAdsClient,
    customer_id: str,
    login_customer_id: str,
    query: str,
    max_response_bytes: int,
) -> Any:
    return await client.post(
        f"customers/{customer_id}/googleAds:searchStream",
        operation=_OPERATION,
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
        max_response_bytes=max_response_bytes,
    )


def _account_today(time_zone: str, now: datetime | None) -> str | None:
    try:
        zone = ZoneInfo(time_zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return (now or datetime.now(UTC)).astimezone(zone).date().isoformat()


def _costs(rows: list[dict[str, Any]], today: str | None) -> tuple[str | None, str]:
    today_micros = 0
    month_micros = 0
    for row in rows:
        metrics = row.get("metrics")
        segments = row.get("segments")
        micros = nonnegative_int(metrics.get("costMicros", 0)) if isinstance(metrics, dict) else 0
        month_micros += micros or 0
        if isinstance(segments, dict) and segments.get("date") == today:
            today_micros += micros or 0
    return (_money(today_micros) if today is not None else None, _money(month_micros))


def _money(micros: int) -> str:
    return format(Decimal(micros).scaleb(-6).normalize(), "f")
