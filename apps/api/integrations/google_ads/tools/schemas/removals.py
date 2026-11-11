# apps/api/integrations/google_ads/tools/schemas/removals.py

"""Arguments and result contract for removing Google Ads objects."""

from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import (
    GoogleAdsAdGroupReference,
    GoogleAdsAdReference,
    GoogleAdsAssetGroupReference,
    GoogleAdsBiddingStrategyReference,
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
    GoogleAdsLabelReference,
    GoogleAdsSharedSetReference,
)
from .base import GoogleAdsStrictModel

# Keyword clean-ups run to hundreds of removals in one call.
MAX_REMOVALS = 500

type GoogleAdsRemovalKind = Literal[
    "campaign",
    "ad_group",
    "ad",
    "keyword",
    "asset_group",
    "budget",
    "label",
    "bidding_strategy",
    "negative_keyword_list",
]
type GoogleAdsRemovalReference = (
    GoogleAdsCampaignReference
    | GoogleAdsAdGroupReference
    | GoogleAdsAdReference
    | GoogleAdsKeywordReference
    | GoogleAdsAssetGroupReference
    | GoogleAdsCampaignBudgetReference
    | GoogleAdsLabelReference
    | GoogleAdsBiddingStrategyReference
    | GoogleAdsSharedSetReference
)


class _Removal(GoogleAdsStrictModel):
    # The `googleAds:mutate` resource type for this kind.
    resource: ClassVar[str]

    @property
    def reference(self) -> GoogleAdsRemovalReference:
        raise NotImplementedError

    @property
    def resource_name(self) -> str:
        raise NotImplementedError


class GoogleAdsCampaignRemoval(_Removal):
    kind: Literal["campaign"]
    campaign: GoogleAdsCampaignReference
    resource: ClassVar[str] = "campaign"

    @property
    def reference(self) -> GoogleAdsCampaignReference:
        return self.campaign

    @property
    def resource_name(self) -> str:
        return f"customers/{self.campaign.customer_id}/campaigns/{self.campaign.campaign_id}"


class GoogleAdsAdGroupRemoval(_Removal):
    kind: Literal["ad_group"]
    ad_group: GoogleAdsAdGroupReference
    resource: ClassVar[str] = "adGroup"

    @property
    def reference(self) -> GoogleAdsAdGroupReference:
        return self.ad_group

    @property
    def resource_name(self) -> str:
        return f"customers/{self.ad_group.customer_id}/adGroups/{self.ad_group.ad_group_id}"


class GoogleAdsAdRemoval(_Removal):
    kind: Literal["ad"]
    ad: GoogleAdsAdReference
    resource: ClassVar[str] = "adGroupAd"

    @property
    def reference(self) -> GoogleAdsAdReference:
        return self.ad

    @property
    def resource_name(self) -> str:
        return self.ad.resource_name


class GoogleAdsKeywordRemoval(_Removal):
    kind: Literal["keyword"]
    keyword: GoogleAdsKeywordReference
    resource: ClassVar[str] = "adGroupCriterion"

    @property
    def reference(self) -> GoogleAdsKeywordReference:
        return self.keyword

    @property
    def resource_name(self) -> str:
        keyword = self.keyword
        return (
            f"customers/{keyword.customer_id}/adGroupCriteria/"
            f"{keyword.ad_group_id}~{keyword.criterion_id}"
        )


class GoogleAdsAssetGroupRemoval(_Removal):
    kind: Literal["asset_group"]
    asset_group: GoogleAdsAssetGroupReference
    resource: ClassVar[str] = "assetGroup"

    @property
    def reference(self) -> GoogleAdsAssetGroupReference:
        return self.asset_group

    @property
    def resource_name(self) -> str:
        return self.asset_group.resource_name


class GoogleAdsBudgetRemoval(_Removal):
    kind: Literal["budget"]
    budget: GoogleAdsCampaignBudgetReference
    resource: ClassVar[str] = "campaignBudget"

    @property
    def reference(self) -> GoogleAdsCampaignBudgetReference:
        return self.budget

    @property
    def resource_name(self) -> str:
        return f"customers/{self.budget.customer_id}/campaignBudgets/{self.budget.budget_id}"


class GoogleAdsLabelRemoval(_Removal):
    kind: Literal["label"]
    label: GoogleAdsLabelReference
    resource: ClassVar[str] = "label"

    @property
    def reference(self) -> GoogleAdsLabelReference:
        return self.label

    @property
    def resource_name(self) -> str:
        return f"customers/{self.label.customer_id}/labels/{self.label.label_id}"


class GoogleAdsBiddingStrategyRemoval(_Removal):
    kind: Literal["bidding_strategy"]
    bidding_strategy: GoogleAdsBiddingStrategyReference
    resource: ClassVar[str] = "biddingStrategy"

    @property
    def reference(self) -> GoogleAdsBiddingStrategyReference:
        return self.bidding_strategy

    @property
    def resource_name(self) -> str:
        return self.bidding_strategy.resource_name


class GoogleAdsNegativeKeywordListRemoval(_Removal):
    kind: Literal["negative_keyword_list"]
    negative_keyword_list: GoogleAdsSharedSetReference
    resource: ClassVar[str] = "sharedSet"

    @property
    def reference(self) -> GoogleAdsSharedSetReference:
        return self.negative_keyword_list

    @property
    def resource_name(self) -> str:
        reference = self.negative_keyword_list
        return f"customers/{reference.customer_id}/sharedSets/{reference.shared_set_id}"


# A plain alias, since the reference-type walker doesn't unwrap `type` statements.
GoogleAdsRemoval = Annotated[
    GoogleAdsCampaignRemoval
    | GoogleAdsAdGroupRemoval
    | GoogleAdsAdRemoval
    | GoogleAdsKeywordRemoval
    | GoogleAdsAssetGroupRemoval
    | GoogleAdsBudgetRemoval
    | GoogleAdsLabelRemoval
    | GoogleAdsBiddingStrategyRemoval
    | GoogleAdsNegativeKeywordListRemoval,
    Field(discriminator="kind"),
]


class GoogleAdsRemoveObjectsRequest(GoogleAdsStrictModel):
    """Every argument of a removal, so an edited approval is checked whole."""

    items: list[GoogleAdsRemoval] = Field(min_length=1, max_length=MAX_REMOVALS)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [item.resource_name for item in self.items]
        if len(set(names)) != len(names):
            raise ValueError("List each item to remove once.")
        return self


class GoogleAdsRemovalDependants(GoogleAdsStrictModel):
    """What a removal takes with it, or for a label, what it is on."""

    campaigns: int = Field(default=0, ge=0)
    ad_groups: int = Field(default=0, ge=0)
    ads: int = Field(default=0, ge=0)
    keywords: int = Field(default=0, ge=0)
    # True when a count stopped at the read bound, so it is a lower bound.
    truncated: bool = False


class GoogleAdsRemovalOutcome(GoogleAdsStrictModel):
    kind: GoogleAdsRemovalKind
    resource_name: str
    name: str
    campaign_name: str | None
    # As the approval card showed it.
    dependants: GoogleAdsRemovalDependants
    outcome: Literal["removed", "already_removed", "failed", "unverified"]
    error_code: str | None = None
    message: str | None = None


class GoogleAdsRemoveObjectsData(GoogleAdsStrictModel):
    account_id: str
    objects: list[GoogleAdsRemovalOutcome] = Field(max_length=MAX_REMOVALS)


class GoogleAdsRemoveObjectsEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemoveObjectsData | None = None


class GoogleAdsRemoveObjectsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemoveObjectsEntry]
