# apps/api/integrations/google_analytics/tools/schemas/google_ads_links.py

"""Contracts for Google Analytics Google Ads links."""

from typing import Annotated, Self

from pydantic import Field, model_validator

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAnalyticsStrictModel


class GoogleAnalyticsGoogleAdsLink(GoogleAnalyticsStrictModel):
    customer_id: Annotated[str, Field(pattern=r"^\d+$", max_length=32)]
    can_manage_clients: bool
    ads_personalization_enabled: bool
    created_at: Annotated[str, Field(max_length=64)] | None = None


class GoogleAnalyticsGoogleAdsLinksData(GoogleAnalyticsStrictModel):
    links: Annotated[list[GoogleAnalyticsGoogleAdsLink], Field(max_length=1000)]
    link_count: Annotated[int, Field(ge=0, le=1000)]

    @model_validator(mode="after")
    def validate_link_count(self) -> Self:
        if self.link_count != len(self.links):
            raise ValueError("link_count must equal the number of links")
        return self


class GoogleAnalyticsListGoogleAdsLinksEntry(IntegrationFanOutEntry):
    data: GoogleAnalyticsGoogleAdsLinksData | None = None


class GoogleAnalyticsListGoogleAdsLinksOutput(IntegrationFanOutOutput):
    results: list[GoogleAnalyticsListGoogleAdsLinksEntry]
