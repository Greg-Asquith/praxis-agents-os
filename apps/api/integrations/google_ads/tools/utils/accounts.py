# apps/api/integrations/google_ads/tools/utils/accounts.py

"""Discovered Google Ads account facts that every write and approval card needs."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_ai import ModelRetry

from services.integrations.context.domain import ResolvedActiveContext, ResolvedContextEntry

from .bindings import GOOGLE_ADS_WRITE_BINDING

# Why an edit tool refuses a change whose approval check didn't cover exactly what was approved.
NOT_SHOWN = (
    "Google Ads couldn't check this before approval, so it wasn't changed. Ask the agent to "
    "prepare the change again."
)


@dataclass(frozen=True, slots=True)
class GoogleAdsAccountFacts:
    customer_id: str
    name: str
    currency: str
    time_zone: str

    def display(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "name": self.name,
            "currency": self.currency,
            "time_zone": self.time_zone,
        }

    def today(self) -> date:
        """Returns the date in the account time zone, or in UTC when Google's zone is unknown."""
        try:
            zone = ZoneInfo(self.time_zone)
        except (ValueError, ZoneInfoNotFoundError):
            zone = UTC
        return datetime.now(zone).date()


def account_facts(entry: ResolvedContextEntry) -> GoogleAdsAccountFacts:
    """Reads the discovered currency and time zone, which discovery stores together."""
    metadata = entry.permissions_metadata
    currency = str(metadata.get("currency_code") or "").strip()
    time_zone = str(metadata.get("time_zone") or "").strip()
    if not currency or not time_zone:
        raise ModelRetry(
            f"Google Ads account {entry.external_id} is missing its currency or time zone. "
            "Refresh the connection and retry."
        )
    return GoogleAdsAccountFacts(
        customer_id=entry.external_id,
        name=entry.display_name,
        currency=currency,
        time_zone=time_zone,
    )


def approval_accounts(entries: Iterable[ResolvedContextEntry]) -> list[dict[str, Any]]:
    """Builds the trusted `_accounts` approval projection for the given accounts."""
    return [account_facts(entry).display() for entry in entries]


def writable_entries(active: ResolvedActiveContext | None) -> dict[str, ResolvedContextEntry]:
    """Returns the accounts in the active context that this run may write to, by customer ID."""
    entries = active.compatible_entries(GOOGLE_ADS_WRITE_BINDING) if active else ()
    return {entry.external_id: entry for entry in entries if entry.write_allowed}


def writable_entry(
    active: ResolvedActiveContext | None, customer_id: str
) -> ResolvedContextEntry | None:
    """Finds the account in the active context that this run may write to, if any."""
    entries = active.compatible_entries(GOOGLE_ADS_WRITE_BINDING) if active else ()
    return next(
        (item for item in entries if item.write_allowed and item.external_id == customer_id),
        None,
    )
