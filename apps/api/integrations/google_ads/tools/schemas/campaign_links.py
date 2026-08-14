# apps/api/integrations/google_ads/tools/schemas/campaign_links.py

"""Result contract for linking negative lists and campaigns."""

from typing import Literal

from integrations.google_ads.references import GoogleAdsSharedSetReference
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel


class GoogleAdsCampaignLinkOutcome(GoogleAdsStrictModel):
    campaign_id: str
    campaign_name: str
    outcome: Literal["linked", "already_linked", "unlinked", "not_linked", "failed"]
    external_ref: str | None = None
    message: str | None = None
    error_code: str | None = None


class GoogleAdsNegativeListSummary(GoogleAdsStrictModel):
    reference: GoogleAdsSharedSetReference
    name: str
    member_count: int | None = None


class GoogleAdsCampaignLinkData(GoogleAdsStrictModel):
    action: Literal["LINK", "UNLINK"]
    negative_list: GoogleAdsNegativeListSummary
    campaigns: list[GoogleAdsCampaignLinkOutcome]


class GoogleAdsCampaignLinkEntry(IntegrationFanOutEntry):
    data: GoogleAdsCampaignLinkData | None = None


class GoogleAdsCampaignLinkOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCampaignLinkEntry]
