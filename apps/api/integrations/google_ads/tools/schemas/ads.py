# apps/api/integrations/google_ads/tools/schemas/ads.py

"""Arguments and result contract for creating Google Ads responsive search ads."""

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsAdGroupReference
from .base import GoogleAdsStrictModel
from .positive_keywords import GoogleAdsFinalUrl

MAX_NEW_ADS = 50
MAX_AD_GROUPS_PER_AD = 10
# Ad groups one request can name across its ads; each is checked before approval.
MAX_AD_GROUPS = 100

type GoogleAdsHeadlinePin = Literal["HEADLINE_1", "HEADLINE_2", "HEADLINE_3"]
type GoogleAdsDescriptionPin = Literal["DESCRIPTION_1", "DESCRIPTION_2"]


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class _TextAsset(GoogleAdsStrictModel):
    @field_validator("text", mode="before", check_fields=False)
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return _strip(value)


class GoogleAdsHeadline(_TextAsset):
    text: str = Field(min_length=1, max_length=30)
    pin: GoogleAdsHeadlinePin | None = Field(
        default=None, description="Always show this headline in one position. Omit to rotate."
    )


class GoogleAdsDescription(_TextAsset):
    text: str = Field(min_length=1, max_length=90)
    pin: GoogleAdsDescriptionPin | None = Field(
        default=None, description="Always show this description in one position. Omit to rotate."
    )


class GoogleAdsResponsiveSearchAd(GoogleAdsStrictModel):
    """One responsive search ad's copy and links, shared by every create tool that makes ads."""

    headlines: list[GoogleAdsHeadline] = Field(min_length=3, max_length=15)
    descriptions: list[GoogleAdsDescription] = Field(min_length=2, max_length=4)
    final_url: GoogleAdsFinalUrl = Field(
        description=(
            "A live page on the advertiser's own site. Google disapproves ads whose page "
            "doesn't load or isn't theirs. Take it from the user or the account's existing "
            "ads; never guess a domain or use a placeholder such as example.com."
        )
    )
    mobile_final_url: GoogleAdsFinalUrl | None = None
    path1: str | None = Field(
        default=None, max_length=15, description="Display URL text after the domain."
    )
    path2: str | None = Field(default=None, max_length=15, description="Needs path1.")

    @field_validator("mobile_final_url", "path1", "path2", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        value = _strip(value)
        return None if value == "" else value

    @model_validator(mode="after")
    def _distinct_copy(self) -> Self:
        for label, texts in (
            ("headline", [item.text for item in self.headlines]),
            ("description", [item.text for item in self.descriptions]),
        ):
            if len(set(texts)) != len(texts):
                raise ValueError(f"Each {label} in an ad must be different.")
        if self.path2 and not self.path1:
            raise ValueError("Set path1 before path2.")
        return self


class GoogleAdsNewAd(GoogleAdsResponsiveSearchAd):
    ad_groups: list[GoogleAdsAdGroupReference] = Field(
        min_length=1,
        max_length=MAX_AD_GROUPS_PER_AD,
        description="Search ad groups to create this ad in; each gets its own copy.",
    )

    @model_validator(mode="after")
    def _each_ad_group_once(self) -> Self:
        ids = [reference.ad_group_id for reference in self.ad_groups]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad group once per ad.")
        return self


class GoogleAdsCreateAdsRequest(GoogleAdsStrictModel):
    """Every argument of an ad creation, so an edited approval is checked whole."""

    ads: list[GoogleAdsNewAd] = Field(min_length=1, max_length=MAX_NEW_ADS)
    status: Literal["PAUSED", "ENABLED"] = "PAUSED"

    @model_validator(mode="after")
    def _one_account(self) -> Self:
        references = [reference for ad in self.ads for reference in ad.ad_groups]
        if len({reference.customer_id for reference in references}) != 1:
            raise ValueError("Create ads in one Google Ads account per request.")
        if len({reference.ad_group_id for reference in references}) > MAX_AD_GROUPS:
            raise ValueError(f"One request can create ads in at most {MAX_AD_GROUPS} ad groups.")
        return self


type GoogleAdsCreatedAdOutcome = Literal["created", "failed", "unverified"]


class GoogleAdsCreatedAd(GoogleAdsStrictModel):
    # The ad's 1-based position in the request; one ad in two ad groups has two rows.
    ad: int = Field(ge=1)
    ad_group: str
    ad_group_name: str
    campaign_name: str | None
    headline: str
    resource_name: str | None
    outcome: GoogleAdsCreatedAdOutcome
    # Read back after creation; null when the read failed or nothing was created.
    status: Literal["ENABLED", "PAUSED", "REMOVED"] | None = None
    review_status: str | None = None
    approval_status: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCreateAdsData(GoogleAdsStrictModel):
    account_id: str
    requested_status: Literal["PAUSED", "ENABLED"]
    ads: list[GoogleAdsCreatedAd] = Field(max_length=MAX_NEW_ADS * MAX_AD_GROUPS_PER_AD)


class GoogleAdsCreateAdsEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateAdsData | None = None


class GoogleAdsCreateAdsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateAdsEntry]
