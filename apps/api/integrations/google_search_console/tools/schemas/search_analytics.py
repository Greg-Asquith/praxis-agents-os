# apps/api/integrations/google_search_console/tools/schemas/search_analytics.py

"""Typed contracts for Search Console performance queries."""

from typing import Literal

from pydantic import Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleSearchConsoleStrictModel

type GoogleSearchConsoleDimension = Literal[
    "query", "page", "country", "device", "searchAppearance", "date"
]
type GoogleSearchConsoleFilterDimension = Literal[
    "query", "page", "country", "device", "searchAppearance"
]
type GoogleSearchConsoleFilterOperator = Literal[
    "equals", "contains", "notContains", "notEquals", "includingRegex", "excludingRegex"
]
type GoogleSearchConsoleSearchType = Literal[
    "web", "image", "video", "news", "discover", "googleNews"
]
type GoogleSearchConsoleAggregationType = Literal["auto", "byPage", "byProperty"]
type GoogleSearchConsoleDataState = Literal["final", "all"]
type GoogleSearchConsoleDimensionValue = str | UntrustedNode


class GoogleSearchConsoleFilter(GoogleSearchConsoleStrictModel):
    dimension: GoogleSearchConsoleFilterDimension
    operator: GoogleSearchConsoleFilterOperator = "equals"
    expression: str = Field(min_length=1, max_length=1_024)


class GoogleSearchConsoleSearchAnalyticsInput(GoogleSearchConsoleStrictModel):
    start_date: str
    end_date: str
    dimensions: list[GoogleSearchConsoleDimension] = Field(default_factory=list, max_length=6)
    search_type: GoogleSearchConsoleSearchType = "web"
    filters: list[GoogleSearchConsoleFilter] | None = Field(default=None, max_length=10)
    aggregation_type: GoogleSearchConsoleAggregationType = "auto"
    row_limit: int = Field(default=100, ge=1)
    start_row: int = Field(default=0, ge=0)
    data_state: GoogleSearchConsoleDataState = "final"


class GoogleSearchConsoleSearchAnalyticsRow(GoogleSearchConsoleStrictModel):
    keys: dict[str, GoogleSearchConsoleDimensionValue]
    clicks: float = Field(ge=0, allow_inf_nan=False)
    impressions: float = Field(ge=0, allow_inf_nan=False)
    ctr: float = Field(ge=0, le=1, allow_inf_nan=False)
    position: float = Field(ge=0, allow_inf_nan=False)


class GoogleSearchConsoleSearchAnalyticsData(GoogleSearchConsoleStrictModel):
    rows: list[GoogleSearchConsoleSearchAnalyticsRow]
    row_count: int = Field(ge=0)
    truncated: bool
    truncation_note: str | None
    response_aggregation_type: str = Field(max_length=128)
    start_date: str
    end_date: str
    search_type: GoogleSearchConsoleSearchType


class GoogleSearchConsoleSearchAnalyticsEntry(IntegrationFanOutEntry):
    data: GoogleSearchConsoleSearchAnalyticsData | None = None


class GoogleSearchConsoleSearchAnalyticsOutput(IntegrationFanOutOutput):
    results: list[GoogleSearchConsoleSearchAnalyticsEntry]
