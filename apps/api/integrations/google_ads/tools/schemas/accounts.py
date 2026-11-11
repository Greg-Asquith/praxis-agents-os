# apps/api/integrations/google_ads/tools/schemas/accounts.py

"""Typed Google Ads account overviews with exact currency amounts."""

from typing import Annotated, Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsAccountBudgetReference, GoogleAdsBillingSetupReference
from .base import GoogleAdsStrictModel

type GoogleAdsMoney = Annotated[str, Field(max_length=32, pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
type GoogleAdsText = Annotated[str, Field(max_length=512)]
# Google's "YYYY-MM-DD HH:MM:SS" in the account time zone.
type GoogleAdsDateTime = Annotated[str, Field(max_length=19)]


class GoogleAdsSpendingLimit(GoogleAdsStrictModel):
    account_budget: GoogleAdsAccountBudgetReference
    # The limit Google enforces after adjustments; null when the limit has no ceiling.
    limit: GoogleAdsMoney | None
    # Spend served against this limit, which can differ from invoiced spend.
    served: GoogleAdsMoney
    left: GoogleAdsMoney | None
    starts: GoogleAdsDateTime | None
    # Null when the limit runs until someone ends it.
    ends: GoogleAdsDateTime | None
    purchase_order_number: GoogleAdsText | None


class GoogleAdsPendingLimitChange(GoogleAdsStrictModel):
    account_budget: GoogleAdsAccountBudgetReference
    kind: Literal["create", "update", "end", "remove", "unknown"]
    # For create and update, null means no ceiling.
    limit: GoogleAdsMoney | None
    starts: GoogleAdsDateTime | None
    ends: GoogleAdsDateTime | None
    submitted: GoogleAdsDateTime | None


class GoogleAdsAccountBilling(GoogleAdsStrictModel):
    # Google Ads reports spending limits only for accounts paid by monthly invoice.
    monthly_invoicing: bool
    state: Literal[
        "not_monthly_invoicing",
        "setup_pending",
        "no_active_limit",
        "active",
        "running_low",
        "limit_reached",
    ]
    billing_setup: GoogleAdsBillingSetupReference | None
    billing_setup_status: GoogleAdsText | None
    payments_account_id: GoogleAdsText | None
    payments_account_name: GoogleAdsText | None
    payments_profile_id: GoogleAdsText | None
    payments_profile_name: GoogleAdsText | None
    active_limit: GoogleAdsSpendingLimit | None
    queued_limits: list[GoogleAdsSpendingLimit] = Field(max_length=200)
    last_ended_limit: GoogleAdsSpendingLimit | None
    pending_changes: list[GoogleAdsPendingLimitChange] = Field(max_length=200)


class GoogleAdsAccountData(GoogleAdsStrictModel):
    customer_id: str = Field(pattern=r"^[0-9]{1,32}$")
    name: GoogleAdsText | None
    status: GoogleAdsText
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    time_zone: GoogleAdsText
    manager: bool
    auto_tagging_enabled: bool | None
    # Manager accounts have no cost or billing of their own, so these are null for them.
    cost_today: GoogleAdsMoney | None
    cost_this_month: GoogleAdsMoney | None
    # Also null when Google refused the billing read, such as for a sign-in with no billing access.
    billing: GoogleAdsAccountBilling | None


class GoogleAdsAccountEntry(IntegrationFanOutEntry):
    data: GoogleAdsAccountData | None = None


class GoogleAdsAccountsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAccountEntry]
