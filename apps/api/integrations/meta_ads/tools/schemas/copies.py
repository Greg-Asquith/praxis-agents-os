# apps/api/integrations/meta_ads/tools/schemas/copies.py

"""Input and result contracts for copying existing ads into other ad sets."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...creative_features import MetaAdsAdFormat
from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdReference, MetaAdsAdSetReference
from .ads import MAX_AD_SETS, MAX_NAME_LENGTH, MetaAdsAdStatusChoice
from .objects import MetaAdsReviewState

MAX_COPIES = 50


def _name(value: str) -> str:
    if not value.strip():
        raise ValueError("Write a name, or leave it out to keep the source ad's name.")
    return value.strip()


class MetaAdsAdCopy(MetaAdsStrictModel):
    """One existing ad copied into one other ad set."""

    ad: MetaAdsAdReference = Field(description="Existing ad to copy.")
    ad_set: MetaAdsAdSetReference = Field(description="Ad set the copy goes in.")
    name: Annotated[str, Field(max_length=MAX_NAME_LENGTH), AfterValidator(_name)] | None = Field(
        default=None, description="Name for the copy; defaults to the source ad's name."
    )
    status: MetaAdsAdStatusChoice = Field(
        default="paused",
        description="paused copies the ad off; active lets it run once Meta approves it.",
    )

    @property
    def key(self) -> str:
        return f"{self.ad.ad_id}:{self.ad_set.adset_id}"


class MetaAdsCopyAdsRequest(MetaAdsStrictModel):
    copies: list[MetaAdsAdCopy] = Field(min_length=1, max_length=MAX_COPIES)

    @model_validator(mode="after")
    def _check_call(self) -> Self:
        accounts = {item.ad.account_id for item in self.copies}
        accounts.update(item.ad_set.account_id for item in self.copies)
        if len(accounts) != 1:
            raise ValueError("Copy ads within one ad account.")
        keys = [item.key for item in self.copies]
        if len(set(keys)) != len(keys):
            raise ValueError("Copy each ad into each ad set once.")
        if any(item.ad.adset_id == item.ad_set.adset_id for item in self.copies):
            raise ValueError("Copy ads into other ad sets, not the one they're already in.")
        if len({item.ad_set.adset_id for item in self.copies}) > MAX_AD_SETS:
            raise ValueError(f"Copy into at most {MAX_AD_SETS} ad sets in one call.")
        return self

    @property
    def account_id(self) -> str:
        return self.copies[0].ad.account_id


type MetaAdsCopiedAdOutcome = Literal["copied", "failed", "unverified"]


class MetaAdsCopiedAd(MetaAdsStrictModel):
    source_ad_id: MetaAdsId
    source_name: MetaAdsText | None
    name: MetaAdsText
    adset_id: MetaAdsId
    adset_name: MetaAdsText | None
    format: MetaAdsAdFormat | None
    requested_status: MetaAdsAdStatusChoice
    # True when the source has an AI-generated change on, so the copy starts off.
    paused_for_ai: bool
    outcome: MetaAdsCopiedAdOutcome
    # True when an unclear reply was settled by finding the copy by name.
    recovered: bool
    # False when the copy couldn't be read back after it was made.
    verified: bool
    ad_id: MetaAdsId | None
    effective_status: MetaAdsText | None
    review: MetaAdsReviewState
    review_reasons: list[MetaAdsText] = Field(max_length=5)
    # Automatic changes Meta shows on the copy that its source didn't have.
    unexpected_changes: list[MetaAdsText] = Field(max_length=40)
    preview_url: str | None = Field(default=None, max_length=2048)
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsCopyAdsData(MetaAdsStrictModel):
    account_id: MetaAdsId
    copies: list[MetaAdsCopiedAd] = Field(max_length=MAX_COPIES)


class MetaAdsCopyAdsEntry(IntegrationFanOutEntry):
    data: MetaAdsCopyAdsData | None = None


class MetaAdsCopyAdsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsCopyAdsEntry]
