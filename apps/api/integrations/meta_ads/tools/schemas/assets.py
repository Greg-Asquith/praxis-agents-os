# apps/api/integrations/meta_ads/tools/schemas/assets.py

"""Pages, Instagram accounts, and media an ad account can use in ads."""

from typing import Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsStrictModel
from ...references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
)

type MetaAdsAssetKind = Literal["pages", "instagram_accounts", "images", "videos"]


class MetaAdsAssetsData(MetaAdsStrictModel):
    pages: list[MetaAdsPageReference] = Field(max_length=100)
    instagram_accounts: list[MetaAdsInstagramAccountReference] = Field(max_length=100)
    images: list[MetaAdsMediaReference] = Field(max_length=50)
    videos: list[MetaAdsMediaReference] = Field(max_length=50)
    # Kinds with more items than were returned.
    truncated: list[MetaAdsAssetKind] = Field(max_length=4)
    notes: list[str] = Field(max_length=4)


class MetaAdsAssetsEntry(IntegrationFanOutEntry):
    data: MetaAdsAssetsData | None = None


class MetaAdsAssetsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsAssetsEntry]
