# apps/api/integrations/google_ads/tools/schemas/scoped_negative_keywords.py

"""Result contracts for campaign and ad-group negative keyword mutations."""

from typing import Literal

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel
from .negative_keywords import GoogleAdsAddKeywordCounts, GoogleAdsRemoveKeywordCounts


class GoogleAdsAddKeywordOutcome(GoogleAdsStrictModel):
    text: str
    match_type: str
    outcome: Literal["added", "skipped_existing", "failed"]
    external_ref: str | None = None
    error_code: str | None = None


class GoogleAdsRemoveKeywordOutcome(GoogleAdsStrictModel):
    text: str
    match_type: str
    outcome: Literal["removed", "not_found", "failed"]
    external_ref: str | None = None
    error_code: str | None = None


class GoogleAdsScopedKeywordError(GoogleAdsStrictModel):
    text: str
    match_type: str
    message: str
    error_code: str


class GoogleAdsAddCampaignKeywordResult(GoogleAdsStrictModel):
    campaign_id: str
    campaign_name: str
    counts: GoogleAdsAddKeywordCounts
    campaign_errors: list[GoogleAdsScopedKeywordError]
    errors_truncated: bool
    keyword_outcomes: list[GoogleAdsAddKeywordOutcome] | None = None


class GoogleAdsRemoveCampaignKeywordResult(GoogleAdsStrictModel):
    campaign_id: str
    campaign_name: str
    counts: GoogleAdsRemoveKeywordCounts
    campaign_errors: list[GoogleAdsScopedKeywordError]
    errors_truncated: bool
    keyword_outcomes: list[GoogleAdsRemoveKeywordOutcome] | None = None


class GoogleAdsAddAdGroupKeywordResult(GoogleAdsStrictModel):
    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    counts: GoogleAdsAddKeywordCounts
    ad_group_errors: list[GoogleAdsScopedKeywordError]
    errors_truncated: bool
    keyword_outcomes: list[GoogleAdsAddKeywordOutcome] | None = None


class GoogleAdsRemoveAdGroupKeywordResult(GoogleAdsStrictModel):
    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    counts: GoogleAdsRemoveKeywordCounts
    ad_group_errors: list[GoogleAdsScopedKeywordError]
    errors_truncated: bool
    keyword_outcomes: list[GoogleAdsRemoveKeywordOutcome] | None = None


class GoogleAdsAddCampaignKeywordData(GoogleAdsStrictModel):
    counts: GoogleAdsAddKeywordCounts
    campaigns: list[GoogleAdsAddCampaignKeywordResult]
    campaigns_truncated: bool


class GoogleAdsRemoveCampaignKeywordData(GoogleAdsStrictModel):
    counts: GoogleAdsRemoveKeywordCounts
    campaigns: list[GoogleAdsRemoveCampaignKeywordResult]
    campaigns_truncated: bool


class GoogleAdsAddAdGroupKeywordData(GoogleAdsStrictModel):
    counts: GoogleAdsAddKeywordCounts
    ad_groups: list[GoogleAdsAddAdGroupKeywordResult]
    ad_groups_truncated: bool


class GoogleAdsRemoveAdGroupKeywordData(GoogleAdsStrictModel):
    counts: GoogleAdsRemoveKeywordCounts
    ad_groups: list[GoogleAdsRemoveAdGroupKeywordResult]
    ad_groups_truncated: bool


class GoogleAdsAddCampaignKeywordEntry(IntegrationFanOutEntry):
    data: GoogleAdsAddCampaignKeywordData | None = None


class GoogleAdsRemoveCampaignKeywordEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemoveCampaignKeywordData | None = None


class GoogleAdsAddAdGroupKeywordEntry(IntegrationFanOutEntry):
    data: GoogleAdsAddAdGroupKeywordData | None = None


class GoogleAdsRemoveAdGroupKeywordEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemoveAdGroupKeywordData | None = None


class GoogleAdsAddCampaignKeywordOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAddCampaignKeywordEntry]


class GoogleAdsRemoveCampaignKeywordOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemoveCampaignKeywordEntry]


class GoogleAdsAddAdGroupKeywordOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAddAdGroupKeywordEntry]


class GoogleAdsRemoveAdGroupKeywordOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemoveAdGroupKeywordEntry]
