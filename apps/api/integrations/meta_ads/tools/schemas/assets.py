# apps/api/integrations/meta_ads/tools/schemas/assets.py

"""Pages, Instagram accounts, media, and posts an ad account can use in ads."""

from typing import Literal

from pydantic import Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsStrictModel
from ...references import (
    MetaAdsInstagramAccountReference,
    MetaAdsMediaReference,
    MetaAdsPageReference,
    MetaAdsPostReference,
)

type MetaAdsAssetKind = Literal["pages", "instagram_accounts", "images", "videos", "posts"]


class MetaAdsPostAsset(MetaAdsStrictModel):
    post: MetaAdsPostReference
    # The post's opening text, written by whoever posted it.
    text: UntrustedNode | None


class MetaAdsAssetsData(MetaAdsStrictModel):
    pages: list[MetaAdsPageReference] = Field(max_length=100)
    instagram_accounts: list[MetaAdsInstagramAccountReference] = Field(max_length=100)
    images: list[MetaAdsMediaReference] = Field(max_length=50)
    videos: list[MetaAdsMediaReference] = Field(max_length=50)
    # 25 per Page and Instagram account, for up to 5 of each.
    posts: list[MetaAdsPostAsset] = Field(max_length=250)
    # Kinds with more items than were returned.
    truncated: list[MetaAdsAssetKind] = Field(max_length=5)
    notes: list[str] = Field(max_length=5)


class MetaAdsAssetsEntry(IntegrationFanOutEntry):
    data: MetaAdsAssetsData | None = None


class MetaAdsAssetsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsAssetsEntry]
