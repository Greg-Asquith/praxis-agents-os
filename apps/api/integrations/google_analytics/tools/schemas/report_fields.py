# apps/api/integrations/google_analytics/tools/schemas/report_fields.py

"""Contracts for Google Analytics report-field discovery and compatibility."""

from typing import Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAnalyticsStrictModel
from .run_report import GoogleAnalyticsFieldFilter

type GoogleAnalyticsCompatibility = Literal["COMPATIBLE", "INCOMPATIBLE"]


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


class GoogleAnalyticsCheckReportFieldsInput(GoogleAnalyticsStrictModel):
    metrics: list[str] = Field(
        max_length=10,
        description="Metric API names in the compatible base report.",
    )
    dimensions: list[str] = Field(
        max_length=9,
        description="Dimension API names in the compatible base report.",
    )
    candidate_metrics: list[str] = Field(
        max_length=10,
        description="Metric API names to check for addition to the base report.",
    )
    candidate_dimensions: list[str] = Field(
        max_length=9,
        description="Dimension API names to check for addition to the base report.",
    )
    dimension_filter: list[GoogleAnalyticsFieldFilter] | None = Field(
        default=None,
        description="Dimension filters included in the proposed report.",
    )
    metric_filter: list[GoogleAnalyticsFieldFilter] | None = Field(
        default=None,
        description="Metric filters included in the proposed report.",
    )

    @model_validator(mode="after")
    def validate_candidates(self) -> Self:
        if not self.candidate_metrics and not self.candidate_dimensions:
            raise ValueError("provide at least one candidate metric or dimension")
        if overlap := set(self.metrics) & set(self.candidate_metrics):
            raise ValueError(
                f"candidate metrics already appear in the base report: {sorted(overlap)}"
            )
        if overlap := set(self.dimensions) & set(self.candidate_dimensions):
            raise ValueError(
                f"candidate dimensions already appear in the base report: {sorted(overlap)}"
            )
        return self


class GoogleAnalyticsFieldCompatibility(GoogleAnalyticsStrictModel):
    api_name: str
    compatibility: GoogleAnalyticsCompatibility


class GoogleAnalyticsReportFieldCompatibilityData(GoogleAnalyticsStrictModel):
    compatible: bool
    dimensions: list[GoogleAnalyticsFieldCompatibility]
    metrics: list[GoogleAnalyticsFieldCompatibility]
    incompatible_fields: list[str]


class GoogleAnalyticsCheckReportFieldsEntry(IntegrationFanOutEntry):
    data: GoogleAnalyticsReportFieldCompatibilityData | None = None


class GoogleAnalyticsCheckReportFieldsOutput(IntegrationFanOutOutput):
    results: list[GoogleAnalyticsCheckReportFieldsEntry]
