# apps/api/integrations/google_ads/tools/schemas/keyword_updates.py

"""Arguments and result contract for changing the bids, URLs, and match types of live keywords."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.campaign_bidding import money
from ...operations.keyword_settings import KeywordSetting
from ...references import GoogleAdsKeywordReference
from ..utils.money import money_to_micros
from .base import GoogleAdsStrictModel
from .campaign_updates import GoogleAdsUrlOptions, GoogleAdsUrlParameter
from .positive_keywords import GoogleAdsCpcBid, GoogleAdsFinalUrl

MAX_KEYWORD_UPDATES = 500

type _UrlList = Annotated[list[GoogleAdsFinalUrl], Field(max_length=10)]


class GoogleAdsKeywordUpdate(GoogleAdsStrictModel):
    """One keyword and only the settings that change."""

    keyword: GoogleAdsKeywordReference
    # A new match type pauses this keyword and adds the same text with it, in one request.
    match_type: Literal["EXACT", "PHRASE", "BROAD"] | None = None
    # "none" removes the keyword's own bid, so it uses its ad group's.
    cpc_bid: Literal["none"] | GoogleAdsCpcBid | None = None
    # An empty list clears the keyword's own URLs, so its ads' URLs apply.
    final_urls: _UrlList | None = None
    final_mobile_urls: _UrlList | None = None
    url_options: GoogleAdsUrlOptions | None = None

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if not self.requested:
            raise ValueError(
                f"Name at least one setting to change for keyword {self.keyword.label}."
            )
        return self

    @property
    def resource_name(self) -> str:
        keyword = self.keyword
        return (
            f"customers/{keyword.customer_id}/adGroupCriteria/"
            f"{keyword.ad_group_id}~{keyword.criterion_id}"
        )

    @property
    def requested(self) -> dict[KeywordSetting, Any]:
        """The settings that change, in card terms: money as a canonical decimal, removal as null."""
        values: dict[KeywordSetting, Any] = {}
        if self.match_type is not None:
            values["match_type"] = self.match_type
        if self.cpc_bid is not None:
            values["cpc_bid"] = (
                None if self.cpc_bid == "none" else money(money_to_micros(self.cpc_bid))
            )
        if self.final_urls is not None:
            values["final_urls"] = list(self.final_urls)
        if self.final_mobile_urls is not None:
            values["final_mobile_urls"] = list(self.final_mobile_urls)
        if self.url_options is not None:
            values.update(self.url_options.requested)
        return values


class GoogleAdsUpdateKeywordsRequest(GoogleAdsStrictModel):
    """Every argument of a keyword update, so an edited approval is checked whole."""

    changes: list[GoogleAdsKeywordUpdate] = Field(min_length=1, max_length=MAX_KEYWORD_UPDATES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [change.resource_name for change in self.changes]
        if len(set(names)) != len(names):
            raise ValueError("List each keyword once, with all of its changes.")
        return self


type GoogleAdsKeywordSettingValue = str | list[str] | list[GoogleAdsUrlParameter] | None


class GoogleAdsKeywordSettingOutcome(GoogleAdsStrictModel):
    setting: KeywordSetting
    # As the approval card showed it.
    before: GoogleAdsKeywordSettingValue
    requested: GoogleAdsKeywordSettingValue
    # Read back after the change; meaningful only when the keyword's `read_back` is true.
    after: GoogleAdsKeywordSettingValue
    outcome: Literal["updated", "already_set", "failed", "unverified"]


class GoogleAdsKeywordUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    text: str
    match_type: str
    ad_group_name: str
    campaign_name: str
    # The keyword added with the new match type, when Google confirmed it.
    replacement: str | None = None
    read_back: bool
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    settings: list[GoogleAdsKeywordSettingOutcome] = Field(max_length=7)
    error_code: str | None = None
    message: str | None = None


class GoogleAdsKeywordUpdateCounts(GoogleAdsStrictModel):
    updated: int = Field(ge=0)
    already_set: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsUpdateKeywordsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    counts: GoogleAdsKeywordUpdateCounts
    # Every keyword on the card; the agent gets only the ones that didn't change.
    keywords: list[GoogleAdsKeywordUpdateOutcome] = Field(max_length=MAX_KEYWORD_UPDATES)
    keywords_truncated: bool = False


class GoogleAdsUpdateKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateKeywordsData | None = None


class GoogleAdsUpdateKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateKeywordsEntry]
