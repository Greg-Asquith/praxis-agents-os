# apps/api/integrations/google_ads/tools/schemas/report_fields.py

"""Result contracts for Google Ads report-field discovery."""

from typing import Annotated

from pydantic import Field

from .base import GoogleAdsStrictModel

type GoogleAdsFieldNames = Annotated[list[str], Field(max_length=100)]


class GoogleAdsReportFieldSummary(GoogleAdsStrictModel):
    name: str
    category: str
    data_type: str
    selectable: bool
    filterable: bool
    sortable: bool
    is_repeated: bool


class GoogleAdsListReportFieldsOutput(GoogleAdsStrictModel):
    api_version: str
    resource: str
    attribute_resources: GoogleAdsFieldNames
    attribute_resource_count: int = Field(ge=0)
    metrics: GoogleAdsFieldNames
    metric_count: int = Field(ge=0)
    segments: GoogleAdsFieldNames
    segment_count: int = Field(ge=0)
    compatibility_truncated: bool
    fields: Annotated[list[GoogleAdsReportFieldSummary], Field(max_length=100)]
    field_count: int = Field(ge=0)
    truncated: bool


class GoogleAdsGetReportFieldOutput(GoogleAdsReportFieldSummary):
    api_version: str
    type_url: str | None
    enum_values: list[str]
    selectable_with: list[str]
    attribute_resources: list[str]
    metrics: list[str]
    segments: list[str]
