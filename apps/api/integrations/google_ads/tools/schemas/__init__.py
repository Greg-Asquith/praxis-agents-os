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
from .campaign_links import GoogleAdsCampaignLinkOutput
from .campaign_status import GoogleAdsCampaignStatusOutput
from .create_negative_keyword_list import GoogleAdsCreateNegativeKeywordListOutput
from .device_bid_modifiers import (
    GoogleAdsDeviceAdjustment,
    GoogleAdsDeviceBidModifierOutput,
)
from .labels import (
    GoogleAdsApplyLabelsOutput,
    GoogleAdsCreateLabelsOutput,
    GoogleAdsLabelDraft,
    GoogleAdsLabelTarget,
    GoogleAdsRemoveLabelsOutput,
)
from .negative_keywords import (
    GoogleAdsAddNegativeKeywordsOutput,
    GoogleAdsRemoveNegativeKeywordsOutput,
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
from .scoped_negative_keywords import (
    GoogleAdsAddAdGroupKeywordOutput,
    GoogleAdsAddCampaignKeywordOutput,
    GoogleAdsRemoveAdGroupKeywordOutput,
    GoogleAdsRemoveCampaignKeywordOutput,
)

__all__ = [
    "GoogleAdsAddAdGroupKeywordOutput",
    "GoogleAdsAddCampaignKeywordOutput",
    "GoogleAdsAddNegativeKeywordsOutput",
    "GoogleAdsApplyLabelsOutput",
    "GoogleAdsApplyRecommendationsOutput",
    "GoogleAdsAssignCampaignBudgetsOutput",
    "GoogleAdsCampaignBudgetAmount",
    "GoogleAdsCampaignBudgetAmountUpdate",
    "GoogleAdsCampaignLinkOutput",
    "GoogleAdsCampaignStatusOutput",
    "GoogleAdsCpcBid",
    "GoogleAdsCreateCampaignBudgetOutput",
    "GoogleAdsCreateLabelsOutput",
    "GoogleAdsCreateNegativeKeywordListOutput",
    "GoogleAdsCreatePositiveKeywordsOutput",
    "GoogleAdsDailyBudgetAmount",
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
    "GoogleAdsRemoveAdGroupKeywordOutput",
    "GoogleAdsRemoveCampaignBudgetsOutput",
    "GoogleAdsRemoveCampaignKeywordOutput",
    "GoogleAdsRemoveLabelsOutput",
    "GoogleAdsRemoveNegativeKeywordsOutput",
    "GoogleAdsReportFieldDetail",
    "GoogleAdsReportFieldSummary",
    "GoogleAdsRunReportOutput",
    "GoogleAdsTotalBudgetAmount",
    "GoogleAdsUpdateCampaignBudgetAmountsOutput",
    "GoogleAdsUpdatePositiveKeywordsOutput",
]
