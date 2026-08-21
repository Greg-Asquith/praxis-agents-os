# apps/api/integrations/google_ads/tools/schemas/device_bid_modifiers.py

"""Input and result contracts for device bid modifier mutations."""

from typing import Literal

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel


class GoogleAdsDeviceAdjustment(GoogleAdsStrictModel):
    device: Literal["DESKTOP", "MOBILE", "TABLET"]
    bid_modifier: float


class GoogleAdsDeviceBidModifierOutcome(GoogleAdsStrictModel):
    device: Literal["DESKTOP", "MOBILE", "TABLET"]
    requested_bid_modifier: float
    previous_bid_modifier: float | None = None
    outcome: Literal["updated", "already_set", "failed"]
    external_ref: str | None = None
    message: str | None = None
    error_code: str | None = None
    note: str | None = None


class GoogleAdsDeviceBidModifierCampaign(GoogleAdsStrictModel):
    campaign_id: str
    campaign_name: str
    bidding_strategy_type: str
    target_cpa_configured: bool
    devices: list[GoogleAdsDeviceBidModifierOutcome]


class GoogleAdsDeviceBidModifierData(GoogleAdsStrictModel):
    campaigns: list[GoogleAdsDeviceBidModifierCampaign]


class GoogleAdsDeviceBidModifierEntry(IntegrationFanOutEntry):
    data: GoogleAdsDeviceBidModifierData | None = None


class GoogleAdsDeviceBidModifierOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsDeviceBidModifierEntry]
