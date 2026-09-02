# apps/api/integrations/google_ads/tools/schemas/campaign_budgets.py

"""Input and result contracts for Google Ads campaign budget actions."""

from typing import Literal

from pydantic import Field

from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleAdsStrictModel


class GoogleAdsDailyBudgetAmount(GoogleAdsStrictModel):
    daily_amount: str = Field(min_length=1, max_length=32)


class GoogleAdsTotalBudgetAmount(GoogleAdsStrictModel):
    total_amount: str = Field(min_length=1, max_length=32)


type GoogleAdsCampaignBudgetAmount = GoogleAdsDailyBudgetAmount | GoogleAdsTotalBudgetAmount


class GoogleAdsCreateCampaignBudgetData(GoogleAdsStrictModel):
    name: str
    period: Literal["DAILY", "CUSTOM_PERIOD"]
    amount: str
    amount_micros: int
    currency_code: str
    delivery_method: Literal["STANDARD", "ACCELERATED"]
    explicitly_shared: bool
    outcome: Literal["created", "failed", "unverified"]
    reference: GoogleAdsCampaignBudgetReference | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCreateCampaignBudgetEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateCampaignBudgetData | None = None


class GoogleAdsCreateCampaignBudgetOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateCampaignBudgetEntry]
