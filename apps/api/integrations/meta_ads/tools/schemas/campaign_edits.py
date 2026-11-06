# apps/api/integrations/meta_ads/tools/schemas/campaign_edits.py

"""Input and result contracts for changing the settings of existing campaigns."""

from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsMoney, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdSetReference, MetaAdsCampaignReference
from .ad_set_edits import MetaAdsSettingValue
from .budgets import MetaAdsBidStrategy, MetaAdsBudgetAmount
from .campaigns import MetaAdsCampaignName

MAX_CAMPAIGN_EDITS = 50
# Meta refuses a bid strategy change on a campaign with more ad sets than this.
MAX_BID_AD_SETS = 70
# Every setting an edit can change, in the order the card and results show them.
type MetaAdsCampaignSetting = Literal[
    "name", "spend_limit", "bid_strategy", "ad_set_bids", "share_between_ad_sets"
]
CAMPAIGN_SETTINGS: tuple[MetaAdsCampaignSetting, ...] = get_args(MetaAdsCampaignSetting.__value__)


class MetaAdsAdSetBid(MetaAdsStrictModel):
    ad_set: MetaAdsAdSetReference
    bid_amount: MetaAdsBudgetAmount


class MetaAdsCampaignEdit(MetaAdsStrictModel):
    """New values for one campaign; an omitted setting stays as it is."""

    campaign: MetaAdsCampaignReference
    name: MetaAdsCampaignName | None = None
    spend_limit: MetaAdsBudgetAmount | Literal["remove"] | None = Field(
        default=None, description="Most the campaign spends over its life, or remove."
    )
    bid_strategy: MetaAdsBidStrategy | None = None
    ad_set_bids: list[MetaAdsAdSetBid] = Field(
        default_factory=list,
        max_length=MAX_BID_AD_SETS,
        description="With bid_cap or cost_per_result_goal: a bid for every ad set.",
    )
    share_between_ad_sets: Literal[False] | None = Field(
        default=None, description="False stops ad sets sharing budget; it can't be turned on."
    )

    @model_validator(mode="after")
    def _one_setting(self) -> Self:
        if not self.settings:
            raise ValueError("Set at least one setting to change for each campaign.")
        if self.ad_set_bids and self.bid_strategy is None:
            raise ValueError("Set bid_strategy with ad_set_bids.")
        ids = [bid.ad_set.adset_id for bid in self.ad_set_bids]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad set's bid once.")
        if any(
            (bid.ad_set.account_id, bid.ad_set.campaign_id)
            != (self.campaign.account_id, self.campaign.campaign_id)
            for bid in self.ad_set_bids
        ):
            raise ValueError("ad_set_bids can only name ad sets in this campaign.")
        return self

    @property
    def settings(self) -> tuple[MetaAdsCampaignSetting, ...]:
        """The settings this edit changes, in display order."""
        return tuple(key for key in CAMPAIGN_SETTINGS if getattr(self, key) not in (None, []))


class MetaAdsUpdateCampaignsRequest(MetaAdsStrictModel):
    """Every argument of a campaign edit, so an edited approval is checked whole."""

    changes: list[MetaAdsCampaignEdit] = Field(min_length=1, max_length=MAX_CAMPAIGN_EDITS)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        ids = [(item.campaign.account_id, item.campaign.campaign_id) for item in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("List each campaign once, with all its changes together.")
        return self


class MetaAdsCampaignSettingChange(MetaAdsStrictModel):
    setting: MetaAdsCampaignSetting
    # Null means not set, such as no spending limit.
    before: MetaAdsSettingValue | None
    requested: MetaAdsSettingValue | None
    # Read back after the change; null when not set, or when it couldn't be read.
    after: MetaAdsSettingValue | None


class MetaAdsAdSetBidChange(MetaAdsStrictModel):
    adset_id: MetaAdsId
    name: MetaAdsText | None
    before: MetaAdsMoney | None
    requested: MetaAdsMoney
    after: MetaAdsMoney | None


class MetaAdsCampaignEditOutcome(MetaAdsStrictModel):
    campaign_id: MetaAdsId
    name: MetaAdsText | None
    # Every setting except the ad set bids, which are listed per ad set.
    changes: list[MetaAdsCampaignSettingChange] = Field(max_length=len(CAMPAIGN_SETTINGS))
    ad_set_bids: list[MetaAdsAdSetBidChange] = Field(
        default_factory=list, max_length=MAX_BID_AD_SETS
    )
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsUpdateCampaignsData(MetaAdsStrictModel):
    account_id: MetaAdsId
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    campaigns: list[MetaAdsCampaignEditOutcome] = Field(max_length=MAX_CAMPAIGN_EDITS)


class MetaAdsUpdateCampaignsEntry(IntegrationFanOutEntry):
    data: MetaAdsUpdateCampaignsData | None = None


class MetaAdsUpdateCampaignsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsUpdateCampaignsEntry]
