# apps/api/integrations/google_ads/tools/schemas/campaign_status.py

"""Result contract for campaign status mutations."""

from typing import Literal

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel


class GoogleAdsCampaignStatusOutcome(GoogleAdsStrictModel):
    campaign_id: str
    campaign_name: str
    requested_status: Literal["ENABLED", "PAUSED"]
    outcome: Literal["updated", "failed"]
    external_ref: str | None = None
    message: str | None = None
    error_code: str | None = None


class GoogleAdsCampaignStatusData(GoogleAdsStrictModel):
    requested_status: Literal["ENABLED", "PAUSED"]
    campaigns: list[GoogleAdsCampaignStatusOutcome]


class GoogleAdsCampaignStatusEntry(IntegrationFanOutEntry):
    data: GoogleAdsCampaignStatusData | None = None


class GoogleAdsCampaignStatusOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCampaignStatusEntry]
