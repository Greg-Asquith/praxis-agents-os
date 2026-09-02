"""Operation-specific Google Ads tool-result contracts."""

from .campaign_budgets import (
    GoogleAdsCampaignBudgetAmount,
    GoogleAdsCampaignBudgetAmountUpdate,
    GoogleAdsCreateCampaignBudgetOutput,
    GoogleAdsDailyBudgetAmount,
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
from .negative_keywords import (
    GoogleAdsAddNegativeKeywordsOutput,
    GoogleAdsRemoveNegativeKeywordsOutput,
)
from .recommendations import (
    GoogleAdsApplyRecommendationsOutput,
    GoogleAdsDismissRecommendationsOutput,
    GoogleAdsRecommendationApplyParameters,
)
from .report_fields import (
    GoogleAdsGetReportFieldOutput,
    GoogleAdsListReportFieldsOutput,
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
    "GoogleAdsApplyRecommendationsOutput",
    "GoogleAdsCampaignBudgetAmount",
    "GoogleAdsCampaignBudgetAmountUpdate",
    "GoogleAdsCampaignLinkOutput",
    "GoogleAdsCampaignStatusOutput",
    "GoogleAdsCreateCampaignBudgetOutput",
    "GoogleAdsCreateNegativeKeywordListOutput",
    "GoogleAdsDailyBudgetAmount",
    "GoogleAdsDeviceAdjustment",
    "GoogleAdsDeviceBidModifierOutput",
    "GoogleAdsDismissRecommendationsOutput",
    "GoogleAdsGetReportFieldOutput",
    "GoogleAdsJsonValue",
    "GoogleAdsListReportFieldsOutput",
    "GoogleAdsRecommendationApplyParameters",
    "GoogleAdsRemoveAdGroupKeywordOutput",
    "GoogleAdsRemoveCampaignKeywordOutput",
    "GoogleAdsRemoveNegativeKeywordsOutput",
    "GoogleAdsReportFieldSummary",
    "GoogleAdsRunReportOutput",
    "GoogleAdsTotalBudgetAmount",
    "GoogleAdsUpdateCampaignBudgetAmountsOutput",
]
