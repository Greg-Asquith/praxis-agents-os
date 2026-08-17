# apps/api/integrations/google_analytics/tools/schemas/realtime.py

"""Typed inputs and result contracts for Google Analytics realtime reports."""

from typing import Self

from pydantic import Field, model_validator

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAnalyticsStrictModel, GoogleAnalyticsValue
from .run_report import (
    GoogleAnalyticsFieldFilter,
    GoogleAnalyticsMetricAggregation,
    GoogleAnalyticsMetricHeader,
    GoogleAnalyticsOrderBy,
)


class GoogleAnalyticsMinuteRange(GoogleAnalyticsStrictModel):
    start_minutes_ago: int = Field(
        ge=0,
        le=29,
        description="Start of the realtime window, from 0 to 29 minutes ago.",
    )
    end_minutes_ago: int = Field(
        ge=0,
        le=29,
        description="End of the realtime window, from 0 to 29 minutes ago.",
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Optional name used to identify this range in two-range results.",
    )

    @model_validator(mode="after")
    def validate_window_order(self) -> Self:
        if self.start_minutes_ago < self.end_minutes_ago:
            raise ValueError("start_minutes_ago must be greater than or equal to end_minutes_ago")
        if self.name is not None and self.name.startswith(("date_range_", "RESERVED_")):
            raise ValueError("name must not begin with date_range_ or RESERVED_")
        return self


class GoogleAnalyticsRunRealtimeReportInput(GoogleAnalyticsStrictModel):
    metrics: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Realtime metric API names returned by the report.",
    )
    dimensions: list[str] = Field(
        max_length=9,
        description="Realtime dimension API names returned by the report; may be empty.",
    )
    minute_ranges: list[GoogleAnalyticsMinuteRange] | None = Field(
        default=None,
        min_length=1,
        max_length=2,
        description="One or two minute ranges; defaults to the last 30 minutes.",
    )
    dimension_filter: list[GoogleAnalyticsFieldFilter] | None = Field(
        default=None,
        description="Dimension filters combined with AND.",
    )
    metric_filter: list[GoogleAnalyticsFieldFilter] | None = Field(
        default=None,
        description="Metric filters combined with AND.",
    )
    order_bys: list[GoogleAnalyticsOrderBy] | None = Field(
        default=None,
        description="Metric or dimension ordering rules.",
    )
    limit: int = Field(default=100, ge=1, description="Maximum rows returned per property.")
    metric_aggregations: list[GoogleAnalyticsMetricAggregation] | None = Field(
        default=None,
        max_length=3,
        description="Optional TOTAL, MINIMUM, or MAXIMUM metric rows.",
    )


class GoogleAnalyticsRealtimeWindow(GoogleAnalyticsStrictModel):
    start_minutes_ago: int
    end_minutes_ago: int


class GoogleAnalyticsRealtimeReportData(GoogleAnalyticsStrictModel):
    rows: list[dict[str, GoogleAnalyticsValue]]
    row_count: int
    truncated: bool
    truncation_note: str | None
    totals: list[dict[str, GoogleAnalyticsValue]]
    maximums: list[dict[str, GoogleAnalyticsValue]]
    minimums: list[dict[str, GoogleAnalyticsValue]]
    metric_headers: list[GoogleAnalyticsMetricHeader]
    dimension_headers: list[str]
    window: list[GoogleAnalyticsRealtimeWindow]


class GoogleAnalyticsRunRealtimeReportEntry(IntegrationFanOutEntry):
    data: GoogleAnalyticsRealtimeReportData | None = None


class GoogleAnalyticsRunRealtimeReportOutput(IntegrationFanOutOutput):
    results: list[GoogleAnalyticsRunRealtimeReportEntry]
