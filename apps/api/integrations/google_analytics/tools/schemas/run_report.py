# apps/api/integrations/google_analytics/tools/schemas/run_report.py

"""Typed inputs and result contracts for Google Analytics reports."""

from typing import Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAnalyticsStrictModel, GoogleAnalyticsValue

type GoogleAnalyticsStringMatchType = Literal[
    "EXACT",
    "BEGINS_WITH",
    "ENDS_WITH",
    "CONTAINS",
    "FULL_REGEXP",
    "PARTIAL_REGEXP",
]
type GoogleAnalyticsNumericOperation = Literal[
    "EQUAL",
    "LESS_THAN",
    "LESS_THAN_OR_EQUAL",
    "GREATER_THAN",
    "GREATER_THAN_OR_EQUAL",
]
type GoogleAnalyticsDimensionOrderType = Literal[
    "ALPHANUMERIC",
    "CASE_INSENSITIVE_ALPHANUMERIC",
    "NUMERIC",
]
type GoogleAnalyticsMetricAggregation = Literal["TOTAL", "MINIMUM", "MAXIMUM"]


class GoogleAnalyticsDateRange(GoogleAnalyticsStrictModel):
    start_date: str = Field(description="Start date as YYYY-MM-DD, today, yesterday, or NdaysAgo.")
    end_date: str = Field(description="End date as YYYY-MM-DD, today, yesterday, or NdaysAgo.")
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Optional name used to identify this range in multi-range results.",
    )


class GoogleAnalyticsStringFilter(GoogleAnalyticsStrictModel):
    match_type: GoogleAnalyticsStringMatchType = Field(
        description="How the dimension value is matched."
    )
    value: str = Field(min_length=1, description="Dimension value to match.")
    case_sensitive: bool = Field(default=False, description="Match letter case exactly.")


class GoogleAnalyticsInListFilter(GoogleAnalyticsStrictModel):
    values: list[str] = Field(
        min_length=1,
        max_length=50,
        description="Dimension values matched as an OR list.",
    )
    case_sensitive: bool = Field(default=False, description="Match letter case exactly.")


class GoogleAnalyticsNumericFilter(GoogleAnalyticsStrictModel):
    operation: GoogleAnalyticsNumericOperation = Field(
        description="Numeric comparison applied to the metric."
    )
    value: float = Field(
        allow_inf_nan=False,
        description="Finite numeric metric value to compare.",
    )


class GoogleAnalyticsBetweenFilter(GoogleAnalyticsStrictModel):
    from_value: float = Field(
        allow_inf_nan=False,
        description="Inclusive finite lower metric value.",
    )
    to_value: float = Field(
        allow_inf_nan=False,
        description="Inclusive finite upper metric value.",
    )


class GoogleAnalyticsFieldFilter(GoogleAnalyticsStrictModel):
    field_name: str = Field(
        pattern=r"^[A-Za-z0-9_:]+$",
        description="Exact Google Analytics API dimension or metric name.",
    )
    negate: bool = Field(default=False, description="Exclude values matching this filter.")
    string_filter: GoogleAnalyticsStringFilter | None = Field(
        default=None,
        description="String comparison for a dimension.",
    )
    in_list_filter: GoogleAnalyticsInListFilter | None = Field(
        default=None,
        description="OR-list comparison for a dimension.",
    )
    numeric_filter: GoogleAnalyticsNumericFilter | None = Field(
        default=None,
        description="Numeric comparison for a metric.",
    )
    between_filter: GoogleAnalyticsBetweenFilter | None = Field(
        default=None,
        description="Inclusive numeric range for a metric.",
    )

    @model_validator(mode="after")
    def require_one_filter(self) -> Self:
        filters = (
            self.string_filter,
            self.in_list_filter,
            self.numeric_filter,
            self.between_filter,
        )
        if sum(value is not None for value in filters) != 1:
            raise ValueError("Provide exactly one filter type")
        return self


class GoogleAnalyticsOrderBy(GoogleAnalyticsStrictModel):
    metric: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_:]+$",
        description="Metric API name to order by.",
    )
    dimension: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_:]+$",
        description="Dimension API name to order by.",
    )
    order_type: GoogleAnalyticsDimensionOrderType | None = Field(
        default=None,
        description="Optional comparison mode for dimension ordering.",
    )
    desc: bool = Field(default=False, description="Sort in descending order.")

    @model_validator(mode="after")
    def require_one_order_field(self) -> Self:
        if (self.metric is None) == (self.dimension is None):
            raise ValueError("Provide exactly one of metric or dimension")
        if self.metric is not None and self.order_type is not None:
            raise ValueError("order_type is available only for dimension ordering")
        return self


class GoogleAnalyticsRunReportInput(GoogleAnalyticsStrictModel):
    metrics: list[str] = Field(
        min_length=1,
        max_length=10,
        description="Metric API names returned by the report.",
    )
    dimensions: list[str] = Field(
        max_length=9,
        description="Dimension API names returned by the report; may be empty.",
    )
    date_ranges: list[GoogleAnalyticsDateRange] = Field(
        min_length=1,
        max_length=4,
        description="One to four date ranges for the report.",
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
    offset: int = Field(default=0, ge=0, description="Zero-based provider row offset.")
    metric_aggregations: list[GoogleAnalyticsMetricAggregation] | None = Field(
        default=None,
        max_length=3,
        description="Optional metric aggregate rows to return.",
    )
    keep_empty_rows: bool = Field(
        default=False,
        description="Include rows whose metric values are all zero.",
    )


class GoogleAnalyticsMetricHeader(GoogleAnalyticsStrictModel):
    name: str
    type: str


class GoogleAnalyticsActiveMetricRestriction(GoogleAnalyticsStrictModel):
    metric_name: str
    restricted_metric_types: list[str]


class GoogleAnalyticsReportMetadata(GoogleAnalyticsStrictModel):
    currency_code: str
    time_zone: str
    sampled: bool
    sampling_notes: list[str]
    active_metric_restrictions: list[GoogleAnalyticsActiveMetricRestriction]
    data_loss_from_other_row: bool
    thresholded: bool
    empty_reason: str | None


class GoogleAnalyticsReportData(GoogleAnalyticsStrictModel):
    rows: list[dict[str, GoogleAnalyticsValue]]
    row_count: int
    truncated: bool
    truncation_note: str | None
    totals: list[dict[str, GoogleAnalyticsValue]]
    maximums: list[dict[str, GoogleAnalyticsValue]]
    minimums: list[dict[str, GoogleAnalyticsValue]]
    metric_headers: list[GoogleAnalyticsMetricHeader]
    dimension_headers: list[str]
    metadata: GoogleAnalyticsReportMetadata


class GoogleAnalyticsRunReportEntry(IntegrationFanOutEntry):
    data: GoogleAnalyticsReportData | None = None


class GoogleAnalyticsRunReportOutput(IntegrationFanOutOutput):
    results: list[GoogleAnalyticsRunReportEntry]
