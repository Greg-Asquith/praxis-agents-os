# apps/api/integrations/google_ads/tools/schemas/status.py

"""Arguments and result contract for turning Google Ads objects on or off."""

from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import (
    GoogleAdsAdGroupReference,
    GoogleAdsAdReference,
    GoogleAdsAssetGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
)
from .base import GoogleAdsStrictModel

MAX_STATUS_CHANGES = 100

type GoogleAdsStatusKind = Literal["campaign", "ad_group", "ad", "keyword", "asset_group"]
# ENABLED turns an object on and PAUSED turns it off; removal is google_ads_remove_objects.
type GoogleAdsRequestedStatus = Literal["ENABLED", "PAUSED"]
type GoogleAdsLiveStatus = Literal["ENABLED", "PAUSED", "REMOVED"]


class _StatusChange(GoogleAdsStrictModel):
    status: GoogleAdsRequestedStatus
    # The `googleAds:mutate` resource type for this kind.
    resource: ClassVar[str]

    @property
    def reference(
        self,
    ) -> (
        GoogleAdsCampaignReference
        | GoogleAdsAdGroupReference
        | GoogleAdsAdReference
        | GoogleAdsKeywordReference
        | GoogleAdsAssetGroupReference
    ):
        raise NotImplementedError

    @property
    def resource_name(self) -> str:
        raise NotImplementedError


class GoogleAdsCampaignStatusChange(_StatusChange):
    kind: Literal["campaign"]
    campaign: GoogleAdsCampaignReference
    resource: ClassVar[str] = "campaign"

    @property
    def reference(self) -> GoogleAdsCampaignReference:
        return self.campaign

    @property
    def resource_name(self) -> str:
        return f"customers/{self.campaign.customer_id}/campaigns/{self.campaign.campaign_id}"


class GoogleAdsAdGroupStatusChange(_StatusChange):
    kind: Literal["ad_group"]
    ad_group: GoogleAdsAdGroupReference
    resource: ClassVar[str] = "adGroup"

    @property
    def reference(self) -> GoogleAdsAdGroupReference:
        return self.ad_group

    @property
    def resource_name(self) -> str:
        return f"customers/{self.ad_group.customer_id}/adGroups/{self.ad_group.ad_group_id}"


class GoogleAdsAdStatusChange(_StatusChange):
    kind: Literal["ad"]
    ad: GoogleAdsAdReference
    resource: ClassVar[str] = "adGroupAd"

    @property
    def reference(self) -> GoogleAdsAdReference:
        return self.ad

    @property
    def resource_name(self) -> str:
        return self.ad.resource_name


class GoogleAdsKeywordStatusChange(_StatusChange):
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


class GoogleAdsAssetGroupStatusChange(_StatusChange):
    kind: Literal["asset_group"]
    asset_group: GoogleAdsAssetGroupReference
    resource: ClassVar[str] = "assetGroup"

    @property
    def reference(self) -> GoogleAdsAssetGroupReference:
        return self.asset_group

    @property
    def resource_name(self) -> str:
        return self.asset_group.resource_name


# A plain alias, since the reference-type walker doesn't unwrap `type` statements.
GoogleAdsStatusChange = Annotated[
    GoogleAdsCampaignStatusChange
    | GoogleAdsAdGroupStatusChange
    | GoogleAdsAdStatusChange
    | GoogleAdsKeywordStatusChange
    | GoogleAdsAssetGroupStatusChange,
    Field(discriminator="kind"),
]


class GoogleAdsUpdateStatusRequest(GoogleAdsStrictModel):
    """Every argument of a status change, so an edited approval is checked whole."""

    changes: list[GoogleAdsStatusChange] = Field(min_length=1, max_length=MAX_STATUS_CHANGES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [change.resource_name for change in self.changes]
        if len(set(names)) != len(names):
            raise ValueError("List each campaign, ad group, ad, keyword, or asset group once.")
        return self


class GoogleAdsStatusOutcome(GoogleAdsStrictModel):
    kind: GoogleAdsStatusKind
    resource_name: str
    name: str
    campaign_id: str | None
    campaign_name: str | None
    # The status shown on the approval card; null when it couldn't be read.
    before: GoogleAdsLiveStatus | None
    requested: GoogleAdsRequestedStatus
    # Read back after the change; null when it wasn't read.
    after: GoogleAdsLiveStatus | None
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateStatusData(GoogleAdsStrictModel):
    account_id: str
    objects: list[GoogleAdsStatusOutcome] = Field(max_length=MAX_STATUS_CHANGES)


class GoogleAdsUpdateStatusEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateStatusData | None = None


class GoogleAdsUpdateStatusOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateStatusEntry]
