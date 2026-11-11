# apps/api/integrations/google_ads/tools/schemas/__init__.py

"""Operation-specific Google Ads tool-result contracts."""

from .labels import (
    GoogleAdsApplyLabelsOutput,
    GoogleAdsCreateLabelsOutput,
    GoogleAdsLabelDraft,
    GoogleAdsLabelTarget,
    GoogleAdsRemoveLabelsOutput,
)
from .positive_keywords import GoogleAdsCpcBid
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
    "GoogleAdsCpcBid",
    "GoogleAdsCreateLabelsOutput",
    "GoogleAdsDismissRecommendationsOutput",
    "GoogleAdsGetReportFieldOutput",
    "GoogleAdsJsonValue",
    "GoogleAdsLabelDraft",
    "GoogleAdsLabelTarget",
    "GoogleAdsListReportFieldsOutput",
    "GoogleAdsRecommendationApplyParameters",
    "GoogleAdsRemoveLabelsOutput",
    "GoogleAdsReportFieldDetail",
    "GoogleAdsReportFieldSummary",
    "GoogleAdsRunReportOutput",
]
