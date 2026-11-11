# apps/api/integrations/google_ads/tools/schemas/ad_groups.py

"""Arguments and result contract for creating Google Ads Search ad groups."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsAdGroupReference, GoogleAdsCampaignReference
from ..utils.money import money_to_micros
from .ads import GoogleAdsResponsiveSearchAd
from .assets import MAX_ASSETS_PER_TARGET, GoogleAdsNewAsset, distinct_new_assets
from .base import GoogleAdsStrictModel, money_validator
from .negative_keywords import NegativeKeywordEntry
from .positive_keywords import (
    GoogleAdsCpcBid,
    GoogleAdsFinalUrl,
    normalize_keyword_text,
    validate_keyword_word_count,
)

MAX_NEW_AD_GROUPS = 20
MAX_KEYWORDS_PER_AD_GROUP = 1_000
MAX_NEGATIVES_PER_AD_GROUP = 500
MAX_ADS_PER_AD_GROUP = 3
# Every object has one audit record, and one audit event holds at most 2,500.
MAX_OBJECTS = 2_500
# Rows in a result that lists what Google refused; an atomic refusal usually gives one reason.
MAX_RESULT_PROBLEMS = 50


def _blank_is_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


class GoogleAdsNewKeyword(GoogleAdsStrictModel):
    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    cpc_bid: GoogleAdsCpcBid | None = None
    final_url: GoogleAdsFinalUrl | None = None

    @field_validator("text", mode="before")
    @classmethod
    def _normalise_text(cls, value: object) -> object:
        return normalize_keyword_text(value)

    @field_validator("text")
    @classmethod
    def _word_count(cls, value: str) -> str:
        return validate_keyword_word_count(value)

    @field_validator("cpc_bid", "final_url", mode="before")
    @classmethod
    def _blank_optional(cls, value: object) -> object:
        return _blank_is_none(value)

    @property
    def cpc_bid_micros(self) -> int | None:
        return money_to_micros(self.cpc_bid) if self.cpc_bid else None


def distinct_keywords(
    entries: list[GoogleAdsNewKeyword] | list[NegativeKeywordEntry], *, scope: str = "ad group"
) -> None:
    pairs = [(entry.text.casefold(), entry.match_type) for entry in entries]
    if len(set(pairs)) != len(pairs):
        raise ValueError(f"List each keyword and match type once per {scope}.")


class GoogleAdsNewAdGroup(GoogleAdsStrictModel):
    """One new Search ad group with what goes in it."""

    name: str = Field(min_length=1, max_length=255)
    cpc_bid: GoogleAdsCpcBid | None = Field(
        default=None,
        description="Default click bid. Only when the campaign uses Manual CPC bidding.",
    )
    target_cpa: Annotated[str, Field(max_length=32), money_validator("target CPA")] | None = Field(
        default=None,
        description=(
            "Overrides the campaign's target CPA, in the account currency. Only when the "
            "campaign uses Target CPA, or Maximise Conversions with a target CPA."
        ),
    )
    target_roas: float | None = Field(
        default=None,
        ge=0.01,
        le=1000,
        description=(
            "Overrides the campaign's target ROAS as a ratio, so 3.5 means 350%. Only when the "
            "campaign uses Target ROAS, or Maximise Conversion Value with a target ROAS, and "
            "not a portfolio strategy."
        ),
    )
    keywords: list[GoogleAdsNewKeyword] = Field(
        default_factory=list, max_length=MAX_KEYWORDS_PER_AD_GROUP
    )
    negative_keywords: list[NegativeKeywordEntry] = Field(
        default_factory=list, max_length=MAX_NEGATIVES_PER_AD_GROUP
    )
    ads: list[GoogleAdsResponsiveSearchAd] = Field(
        default_factory=list, max_length=MAX_ADS_PER_AD_GROUP
    )
    assets: list[GoogleAdsNewAsset] = Field(
        default_factory=list,
        max_length=MAX_ASSETS_PER_TARGET,
        description="New sitelinks and callouts for this ad group alone.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        # Google refuses line breaks in names.
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("cpc_bid", "target_cpa", "target_roas", mode="before")
    @classmethod
    def _blank_optional(cls, value: object) -> object:
        return _blank_is_none(value)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        distinct_keywords(self.keywords)
        distinct_keywords(self.negative_keywords)
        distinct_new_assets(self.assets)
        return self

    @property
    def cpc_bid_micros(self) -> int | None:
        return money_to_micros(self.cpc_bid) if self.cpc_bid else None

    @property
    def target_cpa_micros(self) -> int | None:
        if not self.target_cpa:
            return None
        return money_to_micros(self.target_cpa)

    @property
    def object_count(self) -> int:
        # Each new asset is created and linked.
        return (
            1
            + len(self.keywords)
            + len(self.negative_keywords)
            + len(self.ads)
            + 2 * len(self.assets)
        )


class GoogleAdsCreateAdGroupsRequest(GoogleAdsStrictModel):
    """Every argument of an ad group creation, so an edited approval is checked whole."""

    campaign: GoogleAdsCampaignReference
    ad_groups: list[GoogleAdsNewAdGroup] = Field(min_length=1, max_length=MAX_NEW_AD_GROUPS)
    status: Literal["PAUSED", "ENABLED"] = "PAUSED"

    @model_validator(mode="after")
    def _whole_request(self) -> Self:
        names = [ad_group.name.casefold() for ad_group in self.ad_groups]
        if len(set(names)) != len(names):
            raise ValueError("Give each new ad group a different name.")
        if sum(ad_group.object_count for ad_group in self.ad_groups) > MAX_OBJECTS:
            raise ValueError(f"One request can create at most {MAX_OBJECTS:,} objects.")
        return self


# An asset is a new sitelink or callout, made once however many places link it.
type GoogleAdsBuildKind = Literal[
    "ad_group", "keyword", "negative_keyword", "ad", "asset", "asset_link"
]
type GoogleAdsBuildOutcome = Literal["created", "failed", "unverified"]


class GoogleAdsBuildKindCount(GoogleAdsStrictModel):
    kind: GoogleAdsBuildKind
    created: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsCreatedAdGroup(GoogleAdsStrictModel):
    name: str
    outcome: GoogleAdsBuildOutcome
    # Set when created, for the agent to pass to other tools.
    reference: GoogleAdsAdGroupReference | None = None
    keywords: int = Field(ge=0)
    negative_keywords: int = Field(ge=0)
    ads: int = Field(ge=0)


class GoogleAdsBuildProblemRow(GoogleAdsStrictModel):
    item: str
    kind: GoogleAdsBuildKind
    message: str
    error_code: str | None = None


class GoogleAdsCreateAdGroupsData(GoogleAdsStrictModel):
    account_id: str
    campaign_name: str
    requested_status: Literal["PAUSED", "ENABLED"]
    kinds: list[GoogleAdsBuildKindCount] = Field(max_length=5)
    ad_groups: list[GoogleAdsCreatedAdGroup] = Field(max_length=MAX_NEW_AD_GROUPS)
    problems: list[GoogleAdsBuildProblemRow] = Field(max_length=MAX_RESULT_PROBLEMS)


class GoogleAdsCreateAdGroupsEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateAdGroupsData | None = None


class GoogleAdsCreateAdGroupsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateAdGroupsEntry]
