# apps/api/integrations/google_analytics/tools/schemas/report_fields.py

"""Result contracts for Google Analytics report-field discovery."""

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAnalyticsStrictModel


class GoogleAnalyticsDimensionField(GoogleAnalyticsStrictModel):
    api_name: str
    ui_name: str
    description: str
    category: str
    custom: bool


class GoogleAnalyticsMetricField(GoogleAnalyticsStrictModel):
    api_name: str
    ui_name: str
    description: str
    category: str
    type: str
    custom: bool
    blocked_reasons: list[str]


class GoogleAnalyticsReportFieldsData(GoogleAnalyticsStrictModel):
    dimensions: list[GoogleAnalyticsDimensionField]
    metrics: list[GoogleAnalyticsMetricField]
    dimension_count: int
    metric_count: int
    truncated: bool


class GoogleAnalyticsListReportFieldsEntry(IntegrationFanOutEntry):
    data: GoogleAnalyticsReportFieldsData | None = None


class GoogleAnalyticsListReportFieldsOutput(IntegrationFanOutOutput):
    results: list[GoogleAnalyticsListReportFieldsEntry]
