# apps/api/integrations/google_ads/tools/schemas/assets.py

"""Arguments and result contract for adding, removing, and editing Google Ads ad assets."""

from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.assets import price_offering_value
from ...references import (
    GoogleAdsAdGroupReference,
    GoogleAdsAssetReference,
    GoogleAdsCampaignReference,
)
from ..utils.money import money_to_micros
from .base import GoogleAdsStrictModel, money_validator
from .positive_keywords import GoogleAdsFinalUrl

MAX_ASSET_TARGETS = 100
MAX_ASSETS_PER_TARGET = 20
MAX_ASSET_CHANGES = 20
# Links one request adds and removes across its targets.
MAX_ASSET_LINKS = 1_000
_MAX_OUTCOMES = MAX_ASSET_LINKS + MAX_ASSET_CHANGES
# YouTube video links are pending.
_LINKABLE = frozenset({"SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "PRICE", "IMAGE"})
# Google's English structured snippet headers, which v26 takes as text.
STRUCTURED_SNIPPET_HEADERS = (
    "Amenities",
    "Brands",
    "Courses",
    "Degree programs",
    "Destinations",
    "Featured hotels",
    "Insurance coverage",
    "Models",
    "Neighborhoods",
    "Service catalog",
    "Shows",
    "Styles",
    "Types",
)
_HEADERS = {header.casefold(): header for header in STRUCTURED_SNIPPET_HEADERS}

type GoogleAdsAssetTargetKind = Literal["campaign", "ad_group"]
type GoogleAdsImageFieldType = Literal["AD_IMAGE", "BUSINESS_LOGO"]
type GoogleAdsPriceType = Literal[
    "BRANDS",
    "EVENTS",
    "LOCATIONS",
    "NEIGHBORHOODS",
    "PRODUCT_CATEGORIES",
    "PRODUCT_TIERS",
    "SERVICES",
    "SERVICE_CATEGORIES",
    "SERVICE_TIERS",
]
type GoogleAdsPriceQualifier = Literal["FROM", "UP_TO", "AVERAGE"]
type GoogleAdsPriceUnit = Literal[
    "PER_HOUR", "PER_DAY", "PER_WEEK", "PER_MONTH", "PER_YEAR", "PER_NIGHT"
]


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

    def values_by_path(self) -> dict[str, Any]:
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

    def values_by_path(self) -> dict[str, Any]:
        return {
            "calloutAsset.calloutText": self.text,
            "calloutAsset.startDate": _date(self.start_date),
            "calloutAsset.endDate": _date(self.end_date),
        }


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


class GoogleAdsStructuredSnippet(GoogleAdsStrictModel):
    type: Literal["structured_snippet"]
    header: str = Field(description=f"One of: {', '.join(STRUCTURED_SNIPPET_HEADERS)}.")
    values: list[Annotated[str, Field(min_length=1, max_length=25)]] = Field(
        min_length=3, max_length=10
    )

    @field_validator("header", mode="before")
    @classmethod
    def _known_header(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        header = _HEADERS.get(" ".join(value.split()).casefold())
        if header is None:
            raise ValueError(f"The header must be one of: {', '.join(STRUCTURED_SNIPPET_HEADERS)}.")
        return header

    @field_validator("values", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [_blank_is_none(item) or "" for item in value]

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if len({value.casefold() for value in self.values}) != len(self.values):
            raise ValueError("List each structured snippet value once.")
        return self

    @property
    def asset_type(self) -> str:
        return "STRUCTURED_SNIPPET"

    @property
    def label(self) -> str:
        return f"{self.header}: {', '.join(self.values)}"

    @property
    def key(self) -> str:
        return new_asset_key(self)

    def values_by_path(self) -> dict[str, Any]:
        return {
            "structuredSnippetAsset.header": self.header,
            "structuredSnippetAsset.values": list(self.values),
        }


class GoogleAdsCall(GoogleAdsStrictModel):
    type: Literal["call"]
    country_code: str = Field(
        min_length=2, max_length=2, description="Two-letter country code, such as GB."
    )
    phone_number: str = Field(
        min_length=1, max_length=32, description="The advertiser's own phone number."
    )

    @field_validator("country_code", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("phone_number", mode="before")
    @classmethod
    def _plain_number(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        text = "".join(value.split())
        digits = "".join(char for char in text if char.isdigit())
        if not 6 <= len(digits) <= 16 or any(
            char not in "+-()." for char in text if not char.isdigit()
        ):
            raise ValueError("Enter a phone number of 6 to 16 digits.")
        # Google parses the number with the country code, so only a leading + is kept.
        return f"+{digits}" if text.startswith("+") else digits

    @property
    def asset_type(self) -> str:
        return "CALL"

    @property
    def label(self) -> str:
        return self.phone_number

    @property
    def key(self) -> str:
        return new_asset_key(self)

    def values_by_path(self) -> dict[str, Any]:
        return {
            "callAsset.countryCode": self.country_code,
            "callAsset.phoneNumber": self.phone_number,
        }


class GoogleAdsPriceOffering(GoogleAdsStrictModel):
    header: str = Field(min_length=1, max_length=25)
    description: str = Field(min_length=1, max_length=25)
    price: Annotated[str, Field(max_length=32), money_validator("price")] = Field(
        description="The price in the account currency, such as 49.99."
    )
    unit: GoogleAdsPriceUnit | None = None
    final_url: GoogleAdsFinalUrl = Field(
        description="A page on the advertiser's own site. Never guess a domain."
    )

    @field_validator("header", "description", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        return _blank_is_none(value)


class GoogleAdsPrice(GoogleAdsStrictModel):
    type: Literal["price"]
    price_type: GoogleAdsPriceType
    price_qualifier: GoogleAdsPriceQualifier | None = None
    language_code: str = Field(
        default="en", pattern=r"^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$", description="Such as en."
    )
    currency_code: str = Field(
        pattern=r"^[A-Z]{3}$", description="The account's currency, such as GBP."
    )
    offerings: list[GoogleAdsPriceOffering] = Field(min_length=3, max_length=8)

    @field_validator("currency_code", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _distinct_headers(self) -> Self:
        headers = [offering.header.casefold() for offering in self.offerings]
        if len(set(headers)) != len(headers):
            raise ValueError("Give each price a different header.")
        return self

    @property
    def asset_type(self) -> str:
        return "PRICE"

    @property
    def label(self) -> str:
        return ", ".join(offering.header for offering in self.offerings)

    @property
    def key(self) -> str:
        return new_asset_key(self)

    def values_by_path(self) -> dict[str, Any]:
        return {
            "priceAsset.type": self.price_type,
            "priceAsset.priceQualifier": self.price_qualifier,
            "priceAsset.languageCode": self.language_code,
            "priceAsset.priceOfferings": [
                price_offering_value(
                    {
                        "header": offering.header,
                        "description": offering.description,
                        "price": {
                            "currencyCode": self.currency_code,
                            "amountMicros": str(money_to_micros(offering.price)),
                        },
                        "unit": offering.unit,
                        "finalUrl": offering.final_url,
                    }
                )
                for offering in self.offerings
            ],
        }


class GoogleAdsExistingAsset(GoogleAdsStrictModel):
    type: Literal["existing"]
    asset: GoogleAdsAssetReference
    field_type: GoogleAdsImageFieldType | None = Field(
        default=None,
        description=(
            "For an image only: AD_IMAGE (the default) shows it beside ads; BUSINESS_LOGO, on "
            "campaigns only, shows it as the business logo."
        ),
    )

    @model_validator(mode="after")
    def _image_field_type(self) -> Self:
        if self.field_type is not None and self.asset.asset_type != "IMAGE":
            raise ValueError("Only an image takes a field_type.")
        return self

    @property
    def link_field_type(self) -> str:
        """The field type the link is made with, which for every other asset is its type."""
        if self.asset.asset_type == "IMAGE":
            return self.field_type or "AD_IMAGE"
        return self.asset.asset_type


type NewAsset = (
    GoogleAdsSitelink
    | GoogleAdsCallout
    | GoogleAdsStructuredSnippet
    | GoogleAdsCall
    | GoogleAdsPrice
)

# Plain aliases, since the reference-type walker doesn't unwrap `type` statements.
# The create tools take sitelinks and callouts; Update Ad Assets takes every new type.
GoogleAdsNewAsset = Annotated[GoogleAdsSitelink | GoogleAdsCallout, Field(discriminator="type")]
GoogleAdsAssetContent = Annotated[
    GoogleAdsSitelink
    | GoogleAdsCallout
    | GoogleAdsStructuredSnippet
    | GoogleAdsCall
    | GoogleAdsPrice,
    Field(discriminator="type"),
]
GoogleAdsAssetAddition = Annotated[
    GoogleAdsSitelink
    | GoogleAdsCallout
    | GoogleAdsStructuredSnippet
    | GoogleAdsCall
    | GoogleAdsPrice
    | GoogleAdsExistingAsset,
    Field(discriminator="type"),
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
        description="New assets, or existing ones, to link here.",
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
            raise ValueError("YouTube videos can't be added or removed here.")
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

    @model_validator(mode="after")
    def _no_business_logo(self) -> Self:
        if any(item.type == "existing" and item.field_type == "BUSINESS_LOGO" for item in self.add):
            raise ValueError("A business logo can only be added to a campaign.")
        return self


GoogleAdsAssetTarget = Annotated[
    GoogleAdsCampaignAssets | GoogleAdsAdGroupAssets, Field(discriminator="kind")
]


class GoogleAdsAssetChange(GoogleAdsStrictModel):
    """New content for one existing asset, wherever it's used."""

    asset: GoogleAdsAssetReference
    content: GoogleAdsAssetContent

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


def asset_row_key(item: Any) -> str:
    """Names one asset within a target: an existing asset by ID, a new one by its content."""
    if isinstance(item, GoogleAdsAssetReference):
        return f"asset:{item.asset_id}"
    if isinstance(item, GoogleAdsExistingAsset):
        return f"asset:{item.asset.asset_id}"
    return new_asset_key(item)


def new_asset_key(asset: NewAsset) -> str:
    """Names a new asset by its content, so the same one added to many targets is made once.

    The card builds the same key from the arguments, so the parts are plain text in a fixed order.
    """
    parts: list[str | None]
    match asset:
        case GoogleAdsSitelink():
            parts = [asset.link_text, asset.description1, asset.description2, asset.final_url]
            parts.extend([_date(asset.start_date), _date(asset.end_date)])
        case GoogleAdsCallout():
            parts = [asset.text, _date(asset.start_date), _date(asset.end_date)]
        case GoogleAdsStructuredSnippet():
            parts = [asset.header, *asset.values]
        case GoogleAdsCall():
            parts = [asset.country_code, asset.phone_number]
        case GoogleAdsPrice():
            parts = [asset.price_type, asset.price_qualifier, asset.language_code]
            parts.append(asset.currency_code)
            for offering in asset.offerings:
                parts.extend(
                    [
                        offering.header,
                        offering.description,
                        offering.price,
                        offering.unit,
                        offering.final_url,
                    ]
                )
    return "|".join(["new", asset.type, *(part or "" for part in parts)])


class GoogleAdsAssetOutcome(GoogleAdsStrictModel):
    # Null for an asset's content change, which isn't on one target.
    target_kind: GoogleAdsAssetTargetKind | None = None
    target_name: str | None = None
    action: Literal["add", "remove", "change"]
    asset_type: Literal["SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "PRICE", "IMAGE"]
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
