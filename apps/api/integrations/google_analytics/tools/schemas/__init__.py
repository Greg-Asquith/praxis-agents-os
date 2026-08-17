# apps/api/integrations/google_analytics/tools/schemas/__init__.py

"""Google Analytics tool input and output contracts."""

from .base import GoogleAnalyticsStrictModel, GoogleAnalyticsValue
from .report_fields import GoogleAnalyticsListReportFieldsOutput
from .run_report import (
    GoogleAnalyticsBetweenFilter,
    GoogleAnalyticsDateRange,
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsInListFilter,
    GoogleAnalyticsMetricAggregation,
    GoogleAnalyticsNumericFilter,
    GoogleAnalyticsOrderBy,
    GoogleAnalyticsRunReportInput,
    GoogleAnalyticsRunReportOutput,
    GoogleAnalyticsStringFilter,
)

__all__ = [
    "GoogleAnalyticsBetweenFilter",
    "GoogleAnalyticsDateRange",
    "GoogleAnalyticsFieldFilter",
    "GoogleAnalyticsInListFilter",
    "GoogleAnalyticsListReportFieldsOutput",
    "GoogleAnalyticsMetricAggregation",
    "GoogleAnalyticsNumericFilter",
    "GoogleAnalyticsOrderBy",
    "GoogleAnalyticsRunReportInput",
    "GoogleAnalyticsRunReportOutput",
    "GoogleAnalyticsStrictModel",
    "GoogleAnalyticsStringFilter",
    "GoogleAnalyticsValue",
]
