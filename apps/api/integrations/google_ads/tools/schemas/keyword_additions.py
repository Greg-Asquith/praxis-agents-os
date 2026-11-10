# apps/api/integrations/google_ads/tools/schemas/keyword_additions.py

"""Arguments and result contract for adding keywords to Google Ads ad groups."""

from typing import Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.read_search_terms import keyword_key
from ...references import GoogleAdsAdGroupReference
from .ad_groups import GoogleAdsNewKeyword, distinct_keywords
from .base import GoogleAdsStrictModel

MAX_KEYWORD_ADDITIONS = 1_000
MAX_KEYWORD_AD_GROUPS = 50

type GoogleAdsKeywordAdditionOutcome = Literal["added", "already_set", "failed", "unverified"]


class GoogleAdsKeywordAddition(GoogleAdsStrictModel):
    """The keywords to add to one ad group."""

    ad_group: GoogleAdsAdGroupReference
    keywords: list[GoogleAdsNewKeyword] = Field(min_length=1, max_length=MAX_KEYWORD_ADDITIONS)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        distinct_keywords(self.keywords)
        return self

    @property
    def resource_name(self) -> str:
        return f"customers/{self.ad_group.customer_id}/adGroups/{self.ad_group.ad_group_id}"

    def key(self, keyword: GoogleAdsNewKeyword) -> str:
        """Names the keyword in its ad group, the same way the keyword reads name it."""
        return keyword_key(self.resource_name, keyword.text, keyword.match_type)

    def card_key(self, keyword: GoogleAdsNewKeyword) -> str:
        """Names the keyword on the card, which lower-cases it; case folding turns "ß" into "ss"."""
        return f"{self.resource_name}/{keyword.match_type}/{keyword.text.lower()}"


class GoogleAdsCreateKeywordsRequest(GoogleAdsStrictModel):
    """Every argument of a keyword addition, so an edited approval is checked whole."""

    entries: list[GoogleAdsKeywordAddition] = Field(min_length=1, max_length=MAX_KEYWORD_AD_GROUPS)
    status: Literal["ENABLED", "PAUSED"] = "PAUSED"

    @model_validator(mode="after")
    def _within_limits(self) -> Self:
        names = [entry.resource_name for entry in self.entries]
        if len(set(names)) != len(names):
            raise ValueError("List each ad group once, with all of its keywords.")
        if sum(len(entry.keywords) for entry in self.entries) > MAX_KEYWORD_ADDITIONS:
            raise ValueError(
                f"Add at most {MAX_KEYWORD_ADDITIONS:,} keywords in one call. Split the rest."
            )
        return self


class GoogleAdsAddedKeyword(GoogleAdsStrictModel):
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    cpc_bid: str | None = None
    final_url: str | None = None
    ad_group: str
    ad_group_name: str
    campaign_name: str
    # The new keyword's resource name, once Google confirms it.
    resource_name: str | None = None
    outcome: GoogleAdsKeywordAdditionOutcome
    error_code: str | None = None
    message: str | None = None


class GoogleAdsKeywordAdditionCounts(GoogleAdsStrictModel):
    added: int = Field(ge=0)
    already_set: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsCreateKeywordsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    status: Literal["ENABLED", "PAUSED"]
    counts: GoogleAdsKeywordAdditionCounts
    # Every keyword on the card; the agent gets only the ones that weren't added.
    keywords: list[GoogleAdsAddedKeyword] = Field(max_length=MAX_KEYWORD_ADDITIONS)
    keywords_truncated: bool = False


class GoogleAdsCreateKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateKeywordsData | None = None


class GoogleAdsCreateKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateKeywordsEntry]
