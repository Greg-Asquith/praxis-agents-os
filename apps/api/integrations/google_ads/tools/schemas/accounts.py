# apps/api/integrations/google_ads/tools/schemas/accounts.py

"""Typed Google Ads account overviews with exact currency amounts."""

from typing import Annotated

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleAdsStrictModel

type GoogleAdsMoney = Annotated[str, Field(max_length=32, pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
type GoogleAdsText = Annotated[str, Field(max_length=512)]


class GoogleAdsAccountData(GoogleAdsStrictModel):
    customer_id: str = Field(pattern=r"^[0-9]{1,32}$")
    name: GoogleAdsText | None
    status: GoogleAdsText
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    time_zone: GoogleAdsText
    manager: bool
    auto_tagging_enabled: bool | None
    # Manager accounts have no cost of their own, so both are null for them.
    cost_today: GoogleAdsMoney | None
    cost_this_month: GoogleAdsMoney | None


class GoogleAdsAccountEntry(IntegrationFanOutEntry):
    data: GoogleAdsAccountData | None = None


class GoogleAdsAccountsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAccountEntry]
