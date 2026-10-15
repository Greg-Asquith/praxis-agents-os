# apps/api/integrations/meta_ads/tools/schemas/launch.py

"""Input contract for building a campaign, its ad sets, and their ads in one approval."""

from collections import Counter
from typing import Annotated, Self

from pydantic import Field, model_validator

from ...creative_features import OFFERED_CHANGE_KEYS
from ...models import MetaAdsStrictModel
from ...references import MetaAdsInstagramAccountReference, MetaAdsPageReference
from .ad_sets import MetaAdsAdSetSettings
from .ads import (
    MAX_AD_SETS,
    MAX_ADS,
    MetaAdsAdContent,
    MetaAdsAutomaticChangeKey,
    MetaAdsButton,
    MetaAdsLink,
    MetaAdsUrlTags,
    check_ads,
)
from .campaigns import MetaAdsCreateCampaignRequest

type MetaAdsAdSetKey = Annotated[
    str,
    Field(pattern=r"^[a-z0-9_]{1,40}$", description="Short key such as uk_prospecting."),
]


class MetaAdsLaunchAdSet(MetaAdsAdSetSettings):
    key: MetaAdsAdSetKey


class MetaAdsLaunchAd(MetaAdsAdContent):
    ad_set_keys: list[MetaAdsAdSetKey] = Field(min_length=1, max_length=MAX_AD_SETS)


class MetaAdsLaunchCampaignRequest(MetaAdsStrictModel):
    """Every argument of a launch; shared ad values apply unless an ad sets its own."""

    campaign: MetaAdsCreateCampaignRequest
    ad_sets: list[MetaAdsLaunchAdSet] = Field(min_length=1, max_length=MAX_AD_SETS)
    ads: list[MetaAdsLaunchAd] = Field(min_length=1, max_length=MAX_ADS)
    page: MetaAdsPageReference
    instagram_account: MetaAdsInstagramAccountReference | None = None
    link: MetaAdsLink | None = None
    call_to_action: MetaAdsButton | None = None
    url_tags: MetaAdsUrlTags | None = None
    automatic_changes: list[MetaAdsAutomaticChangeKey] | None = Field(
        default=None, max_length=len(OFFERED_CHANGE_KEYS)
    )
    # Turns the ad sets and then the campaign on once everything is built and confirmed.
    go_live: bool = False

    @model_validator(mode="after")
    def _check_launch(self) -> Self:
        keys = [ad_set.key for ad_set in self.ad_sets]
        if len(set(keys)) != len(keys):
            raise ValueError("Give each ad set a different key.")
        # A lost create is found by name in its campaign, so names must differ.
        names = Counter(ad_set.name.casefold() for ad_set in self.ad_sets)
        if any(count > 1 for count in names.values()):
            raise ValueError("Give each ad set a different name.")
        used = {key for ad in self.ads for key in ad.ad_set_keys}
        if unknown := sorted(used - set(keys)):
            raise ValueError(f"No ad set has the key {unknown[0]}.")
        if empty := [ad_set.name for ad_set in self.ad_sets if ad_set.key not in used]:
            raise ValueError(f"The ad set {empty[0]} needs at least one ad.")
        if any(ad.status is not None for ad in self.ads):
            raise ValueError("Go Live sets every ad's status, so leave status off each ad.")
        accounts = {account for ad_set in self.ad_sets for account in ad_set.asset_accounts}
        check_ads(self, [ad.ad_set_keys for ad in self.ads], accounts=accounts)
        return self

    @property
    def account_id(self) -> str:
        return self.page.account_id

    @property
    def instagram_user_id(self) -> str | None:
        return self.instagram_account.instagram_user_id if self.instagram_account else None
