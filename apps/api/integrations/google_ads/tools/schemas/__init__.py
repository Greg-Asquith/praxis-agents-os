# apps/api/integrations/google_ads/tools/schemas/__init__.py

"""Provider-wide Google Ads tool-result contracts."""

from uuid import UUID

from pydantic import BaseModel

type GoogleAdsJsonValue = (
    str | int | float | bool | list["GoogleAdsJsonValue"] | dict[str, "GoogleAdsJsonValue"] | None
)


class GoogleAdsFanOutEntry(BaseModel):
    integration_resource_id: UUID
    connection_id: UUID
    provider_key: str
    external_id: str
    display_name: str
    status: str
    data: dict[str, GoogleAdsJsonValue] | None = None
    error_code: str | None = None
    error_message: str | None = None


class GoogleAdsOutput(BaseModel):
    results: list[GoogleAdsFanOutEntry]
