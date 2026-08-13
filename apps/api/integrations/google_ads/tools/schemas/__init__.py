# apps/api/integrations/google_ads/tools/schemas/__init__.py

"""Provider-wide Google Ads tool-result contracts."""

from pydantic import BaseModel

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

type GoogleAdsJsonValue = (
    str | int | float | bool | list["GoogleAdsJsonValue"] | dict[str, "GoogleAdsJsonValue"] | None
)


class GoogleAdsFanOutEntry(IntegrationFanOutEntry):
    data: dict[str, GoogleAdsJsonValue] | None = None


class GoogleAdsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsFanOutEntry]


class GoogleAdsReportData(BaseModel):
    currency_code: str
    rows: list[dict[str, GoogleAdsJsonValue]]
    row_count: int
    truncated: bool
    truncation_note: str | None


class GoogleAdsRunReportEntry(IntegrationFanOutEntry):
    data: GoogleAdsReportData | None = None


class GoogleAdsRunReportOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRunReportEntry]
