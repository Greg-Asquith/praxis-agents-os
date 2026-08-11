# apps/api/integrations/google_ads/tools/schemas/__init__.py

"""Provider-wide Google Ads tool-result contracts."""

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
