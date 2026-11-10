# apps/api/integrations/google_ads/tools/schemas/__init__.py

"""Operation-specific Google Ads tool-result contracts."""

from .campaign_budgets import (
    GoogleAdsAssignCampaignBudgetsOutput,
    GoogleAdsCampaignBudgetAmount,
    GoogleAdsCampaignBudgetAmountUpdate,
    GoogleAdsCreateCampaignBudgetOutput,
    GoogleAdsDailyBudgetAmount,
    GoogleAdsRemoveCampaignBudgetsOutput,
    GoogleAdsTotalBudgetAmount,
    GoogleAdsUpdateCampaignBudgetAmountsOutput,
)
from .device_bid_modifiers import (
    GoogleAdsDeviceAdjustment,
    GoogleAdsDeviceBidModifierOutput,
)
from .labels import (
    GoogleAdsApplyLabelsOutput,
    GoogleAdsCreateLabelsOutput,
    GoogleAdsDeleteLabelsOutput,
    GoogleAdsLabelDraft,
    GoogleAdsLabelTarget,
    GoogleAdsRemoveLabelsOutput,
)
from .positive_keywords import (
    GoogleAdsCpcBid,
    GoogleAdsCreatePositiveKeywordsOutput,
    GoogleAdsPositiveKeywordEntry,
    GoogleAdsPositiveKeywordPatch,
    GoogleAdsUpdatePositiveKeywordsOutput,
)
from .recommendations import (
    GoogleAdsApplyRecommendationsOutput,
    GoogleAdsDismissRecommendationsOutput,
    GoogleAdsRecommendationApplyParameters,
)
from .report_fields import (
    GoogleAdsGetReportFieldOutput,
    GoogleAdsListReportFieldsOutput,
    GoogleAdsReportFieldDetail,
    GoogleAdsReportFieldSummary,
)
from .run_report import GoogleAdsJsonValue, GoogleAdsRunReportOutput

__all__ = [
    "GoogleAdsApplyLabelsOutput",
    "GoogleAdsApplyRecommendationsOutput",
    "GoogleAdsAssignCampaignBudgetsOutput",
    "GoogleAdsCampaignBudgetAmount",
    "GoogleAdsCampaignBudgetAmountUpdate",
    "GoogleAdsCpcBid",
    "GoogleAdsCreateCampaignBudgetOutput",
    "GoogleAdsCreateLabelsOutput",
    "GoogleAdsCreatePositiveKeywordsOutput",
    "GoogleAdsDailyBudgetAmount",
    "GoogleAdsDeleteLabelsOutput",
    "GoogleAdsDeviceAdjustment",
    "GoogleAdsDeviceBidModifierOutput",
    "GoogleAdsDismissRecommendationsOutput",
    "GoogleAdsGetReportFieldOutput",
    "GoogleAdsJsonValue",
    "GoogleAdsLabelDraft",
    "GoogleAdsLabelTarget",
    "GoogleAdsListReportFieldsOutput",
    "GoogleAdsPositiveKeywordEntry",
    "GoogleAdsPositiveKeywordPatch",
    "GoogleAdsRecommendationApplyParameters",
    "GoogleAdsRemoveCampaignBudgetsOutput",
    "GoogleAdsRemoveLabelsOutput",
    "GoogleAdsReportFieldDetail",
    "GoogleAdsReportFieldSummary",
    "GoogleAdsRunReportOutput",
    "GoogleAdsTotalBudgetAmount",
    "GoogleAdsUpdateCampaignBudgetAmountsOutput",
    "GoogleAdsUpdatePositiveKeywordsOutput",
]
