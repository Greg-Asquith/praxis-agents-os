# apps/api/integrations/google_ads/tools/schemas/assets.py

"""Arguments and result contract for adding, removing, and editing Google Ads sitelinks and callouts."""

from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import (
    GoogleAdsAdGroupReference,
    GoogleAdsAssetReference,
    GoogleAdsCampaignReference,
)
from .base import GoogleAdsStrictModel
from .positive_keywords import GoogleAdsFinalUrl

MAX_ASSET_TARGETS = 100
MAX_ASSETS_PER_TARGET = 20
MAX_ASSET_CHANGES = 20
# Links one request adds and removes across its targets.
MAX_ASSET_LINKS = 1_000
_MAX_OUTCOMES = MAX_ASSET_LINKS + MAX_ASSET_CHANGES
# Image and video links are pending (309 B).
_LINKABLE = frozenset({"SITELINK", "CALLOUT"})

type GoogleAdsAssetTargetKind = Literal["campaign", "ad_group"]


def _blank_is_none(value: object) -> object:
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


class _Dated(GoogleAdsStrictModel):
    start_date: date | None = Field(
        default=None, description="First day it can show, in the account's time zone."
    )
    end_date: date | None = Field(default=None, description="Last day it can show.")

    @model_validator(mode="after")
    def _dates_in_order(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date must be on or after the start date.")
        return self


class GoogleAdsSitelink(_Dated):
    type: Literal["sitelink"]
    link_text: str = Field(min_length=1, max_length=25)
    description1: str | None = Field(default=None, max_length=35)
    description2: str | None = Field(default=None, max_length=35)
    final_url: GoogleAdsFinalUrl = Field(
        description="A page on the advertiser's own site. Never guess a domain."
    )

    @field_validator("link_text", "description1", "description2", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        return _blank_is_none(value)

    @model_validator(mode="after")
    def _descriptions_paired(self) -> Self:
        if (self.description1 is None) != (self.description2 is None):
            raise ValueError("A sitelink needs both description lines or neither.")
        return self

    @property
    def asset_type(self) -> str:
        return "SITELINK"

    @property
    def label(self) -> str:
        return self.link_text

    @property
    def key(self) -> str:
        return new_asset_key(self)

    def values(self) -> dict[str, Any]:
        """The fields by the edit seam's paths, as Google returns them."""
        return {
            "sitelinkAsset.linkText": self.link_text,
            "sitelinkAsset.description1": self.description1,
            "sitelinkAsset.description2": self.description2,
            "finalUrls": [self.final_url],
            "sitelinkAsset.startDate": _date(self.start_date),
            "sitelinkAsset.endDate": _date(self.end_date),
        }


class GoogleAdsCallout(_Dated):
    type: Literal["callout"]
    text: str = Field(min_length=1, max_length=25)

    @field_validator("text", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        return _blank_is_none(value)

    @property
    def asset_type(self) -> str:
        return "CALLOUT"

    @property
    def label(self) -> str:
        return self.text

    @property
    def key(self) -> str:
        return new_asset_key(self)

    def values(self) -> dict[str, Any]:
        return {
            "calloutAsset.calloutText": self.text,
            "calloutAsset.startDate": _date(self.start_date),
            "calloutAsset.endDate": _date(self.end_date),
        }


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


class GoogleAdsExistingAsset(GoogleAdsStrictModel):
    type: Literal["existing"]
    asset: GoogleAdsAssetReference


# Plain aliases, since the reference-type walker doesn't unwrap `type` statements.
GoogleAdsNewAsset = Annotated[GoogleAdsSitelink | GoogleAdsCallout, Field(discriminator="type")]
GoogleAdsAssetAddition = Annotated[
    GoogleAdsSitelink | GoogleAdsCallout | GoogleAdsExistingAsset, Field(discriminator="type")
]


def distinct_new_assets(assets: list[GoogleAdsSitelink | GoogleAdsCallout]) -> None:
    """Refuses the same sitelink or callout twice in one campaign or ad group."""
    keys = [asset.key for asset in assets]
    if len(set(keys)) != len(keys):
        raise ValueError("List each sitelink and callout once.")


class _AssetTarget(GoogleAdsStrictModel):
    add: list[GoogleAdsAssetAddition] = Field(
        default_factory=list,
        max_length=MAX_ASSETS_PER_TARGET,
        description="New sitelinks and callouts, or existing assets, to link here.",
    )
    remove: list[GoogleAdsAssetReference] = Field(
        default_factory=list,
        max_length=MAX_ASSETS_PER_TARGET,
        description="Assets to unlink from here. The asset stays in the account.",
    )

    @property
    def customer_id(self) -> str:
        raise NotImplementedError

    @property
    def target_key(self) -> str:
        raise NotImplementedError

    @property
    def link_count(self) -> int:
        return len(self.add) + len(self.remove)

    @model_validator(mode="after")
    def _each_asset_once(self) -> Self:
        if not self.add and not self.remove:
            raise ValueError("Each target needs at least one asset to add or remove.")
        keys = [asset_row_key(item) for item in (*self.add, *self.remove)]
        if len(set(keys)) != len(keys):
            raise ValueError("List each asset once per target.")
        existing = (*self.remove, *(i.asset for i in self.add if i.type == "existing"))
        if any(reference.customer_id != self.customer_id for reference in existing):
            raise ValueError("A target can only use assets in its own account.")
        if any(reference.asset_type not in _LINKABLE for reference in existing):
            raise ValueError("Only sitelinks and callouts can be added or removed here.")
        return self


class GoogleAdsCampaignAssets(_AssetTarget):
    kind: Literal["campaign"]
    campaign: GoogleAdsCampaignReference

    @property
    def customer_id(self) -> str:
        return self.campaign.customer_id

    @property
    def target_key(self) -> str:
        return f"customers/{self.customer_id}/campaigns/{self.campaign.campaign_id}"


class GoogleAdsAdGroupAssets(_AssetTarget):
    kind: Literal["ad_group"]
    ad_group: GoogleAdsAdGroupReference

    @property
    def customer_id(self) -> str:
        return self.ad_group.customer_id

    @property
    def target_key(self) -> str:
        return f"customers/{self.customer_id}/adGroups/{self.ad_group.ad_group_id}"


GoogleAdsAssetTarget = Annotated[
    GoogleAdsCampaignAssets | GoogleAdsAdGroupAssets, Field(discriminator="kind")
]


class GoogleAdsAssetChange(GoogleAdsStrictModel):
    """New content for one sitelink or callout, wherever it's used."""

    asset: GoogleAdsAssetReference
    content: GoogleAdsNewAsset

    @model_validator(mode="after")
    def _same_type(self) -> Self:
        if self.asset.asset_type != self.content.asset_type:
            raise ValueError("The new content must be the same type as the asset.")
        return self


class GoogleAdsUpdateAssetsRequest(GoogleAdsStrictModel):
    """Every argument of an asset change, so an edited approval is checked whole."""

    entries: list[GoogleAdsAssetTarget] = Field(default_factory=list, max_length=MAX_ASSET_TARGETS)
    change: list[GoogleAdsAssetChange] = Field(default_factory=list, max_length=MAX_ASSET_CHANGES)

    @model_validator(mode="after")
    def _within_limits(self) -> Self:
        if not self.entries and not self.change:
            raise ValueError("Add, remove, or change at least one asset.")
        targets = [entry.target_key for entry in self.entries]
        if len(set(targets)) != len(targets):
            raise ValueError("List each campaign and ad group once.")
        assets = [item.asset.asset_id for item in self.change]
        if len(set(assets)) != len(assets):
            raise ValueError("Change each asset once.")
        if sum(entry.link_count for entry in self.entries) > MAX_ASSET_LINKS:
            raise ValueError(
                f"One request can add or remove at most {MAX_ASSET_LINKS:,} asset links."
            )
        return self

    @property
    def customer_ids(self) -> list[str]:
        ids = [entry.customer_id for entry in self.entries]
        ids.extend(item.asset.customer_id for item in self.change)
        return list(dict.fromkeys(ids))


def asset_row_key(item: Any) -> str:
    """Names one asset within a target: an existing asset by ID, a new one by its content."""
    if isinstance(item, GoogleAdsAssetReference):
        return f"asset:{item.asset_id}"
    if isinstance(item, GoogleAdsExistingAsset):
        return f"asset:{item.asset.asset_id}"
    return new_asset_key(item)


def new_asset_key(asset: GoogleAdsSitelink | GoogleAdsCallout) -> str:
    """Names a new asset by its content, so the same one added to many targets is made once.

    The card builds the same key from the arguments, so the parts are plain text in a fixed order.
    """
    if isinstance(asset, GoogleAdsSitelink):
        parts = [asset.link_text, asset.description1, asset.description2, asset.final_url]
    else:
        parts = [asset.text]
    parts.extend([_date(asset.start_date), _date(asset.end_date)])
    return "|".join(["new", asset.type, *(part or "" for part in parts)])


class GoogleAdsAssetOutcome(GoogleAdsStrictModel):
    # Null for an asset's content change, which isn't on one target.
    target_kind: GoogleAdsAssetTargetKind | None = None
    target_name: str | None = None
    action: Literal["add", "remove", "change"]
    asset_type: Literal["SITELINK", "CALLOUT"]
    asset_label: str
    outcome: Literal[
        "added", "removed", "changed", "already_set", "not_found", "failed", "unverified"
    ]
    error_code: str | None = None
    message: str | None = None


class GoogleAdsAssetCounts(GoogleAdsStrictModel):
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    changed: int = Field(ge=0)
    already_set: int = Field(ge=0)
    not_found: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsUpdateAssetsData(GoogleAdsStrictModel):
    account_id: str
    counts: GoogleAdsAssetCounts
    # Every change on the card; the agent gets only the ones that didn't happen.
    outcomes: list[GoogleAdsAssetOutcome] = Field(max_length=_MAX_OUTCOMES)
    outcomes_truncated: bool = False


class GoogleAdsUpdateAssetsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateAssetsData | None = None


class GoogleAdsUpdateAssetsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateAssetsEntry]
