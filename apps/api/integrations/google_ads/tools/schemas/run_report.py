# apps/api/integrations/google_ads/tools/schemas/run_report.py

"""Result contract for dynamic Google Ads reports."""

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel

type GoogleAdsJsonValue = (
    str | int | float | bool | list["GoogleAdsJsonValue"] | dict[str, "GoogleAdsJsonValue"] | None
)


class GoogleAdsReportData(GoogleAdsStrictModel):
    currency_code: str
    rows: list[dict[str, GoogleAdsJsonValue]]
    row_count: int
    truncated: bool
    truncation_note: str | None


class GoogleAdsRunReportEntry(IntegrationFanOutEntry):
    data: GoogleAdsReportData | None = None


class GoogleAdsRunReportOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRunReportEntry]
