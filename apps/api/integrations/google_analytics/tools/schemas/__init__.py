# apps/api/integrations/google_analytics/tools/schemas/__init__.py

"""Google Analytics tool input and output contracts."""

from .base import GoogleAnalyticsStrictModel, GoogleAnalyticsValue
from .realtime import (
    GoogleAnalyticsMinuteRange,
    GoogleAnalyticsRunRealtimeReportInput,
    GoogleAnalyticsRunRealtimeReportOutput,
)
from .report_fields import (
    GoogleAnalyticsCheckReportFieldsInput,
    GoogleAnalyticsCheckReportFieldsOutput,
    GoogleAnalyticsFieldCompatibility,
    GoogleAnalyticsListReportFieldsOutput,
)
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
    "GoogleAnalyticsCheckReportFieldsInput",
    "GoogleAnalyticsCheckReportFieldsOutput",
    "GoogleAnalyticsDateRange",
    "GoogleAnalyticsFieldCompatibility",
    "GoogleAnalyticsFieldFilter",
    "GoogleAnalyticsInListFilter",
    "GoogleAnalyticsListReportFieldsOutput",
    "GoogleAnalyticsMetricAggregation",
    "GoogleAnalyticsMinuteRange",
    "GoogleAnalyticsNumericFilter",
    "GoogleAnalyticsOrderBy",
    "GoogleAnalyticsRunRealtimeReportInput",
    "GoogleAnalyticsRunRealtimeReportOutput",
    "GoogleAnalyticsRunReportInput",
    "GoogleAnalyticsRunReportOutput",
    "GoogleAnalyticsStrictModel",
    "GoogleAnalyticsStringFilter",
    "GoogleAnalyticsValue",
]
