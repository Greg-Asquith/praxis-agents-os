# apps/api/integrations/google_ads/operations/get_account.py

"""Read one Google Ads account's settings, this month's cost, and its billing."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.exceptions.integration import IntegrationError, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient
from .account_billing import read_account_billing
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
    name = str(customer.get("descriptiveName") or "").strip() or None
    cost_today = cost_this_month = billing = None
    # Manager accounts have no cost, billing setup, or spending limit of their own.
    if not manager:
        local_now = _account_now(time_zone, now)
        cost_rows = stream_rows(
            await _search(client, customer_id, login_customer_id, _COST_QUERY, max_response_bytes)
        )
        today_micros, month_micros = _costs(cost_rows, local_now)
        cost_today = _money(today_micros) if local_now is not None else None
        cost_this_month = _money(month_micros)
        try:
            billing = await read_account_billing(
                client,
                customer_id=customer_id,
                account_name=name or customer_id,
                login_customer_id=login_customer_id,
                max_response_bytes=max_response_bytes,
                local_now=local_now or (now or datetime.now(UTC)),
                cost_this_month_micros=month_micros,
            )
        except IntegrationError:
            # The account's settings and costs are still worth returning without billing.
            billing = None
    auto_tagging = customer.get("autoTaggingEnabled")
    return {
        "customer_id": customer_id,
        "name": name,
        "status": str(customer.get("status") or "UNKNOWN"),
        "currency": currency,
        "time_zone": time_zone,
        "manager": manager,
        "auto_tagging_enabled": auto_tagging if isinstance(auto_tagging, bool) else None,
        "cost_today": cost_today,
        "cost_this_month": cost_this_month,
        "billing": billing,
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


def _account_now(time_zone: str, now: datetime | None) -> datetime | None:
    try:
        zone = ZoneInfo(time_zone)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return (now or datetime.now(UTC)).astimezone(zone)


def _costs(rows: list[dict[str, Any]], local_now: datetime | None) -> tuple[int, int]:
    today = local_now.date().isoformat() if local_now is not None else None
    today_micros = 0
    month_micros = 0
    for row in rows:
        metrics = row.get("metrics")
        segments = row.get("segments")
        micros = nonnegative_int(metrics.get("costMicros", 0)) if isinstance(metrics, dict) else 0
        month_micros += micros or 0
        if isinstance(segments, dict) and segments.get("date") == today:
            today_micros += micros or 0
    return today_micros, month_micros


def _money(micros: int) -> str:
    return format(Decimal(micros).scaleb(-6).normalize(), "f")
