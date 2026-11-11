# apps/api/integrations/google_ads/tools/schemas/keyword_research.py

"""Result contract for Google Ads keyword research."""

from typing import Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.keyword_research import MAX_CLOSE_VARIANTS, MAX_THEMES_PER_KEYWORD
from .accounts import GoogleAdsMoney, GoogleAdsText
from .base import GoogleAdsStrictModel

MAX_RESEARCH_ROWS = 1_000
MAX_RESEARCH_LOCATIONS = 10
MAX_RESEARCH_AD_GROUPS = 20


class GoogleAdsResearchPlace(GoogleAdsStrictModel):
    key: str = Field(max_length=20)
    name: GoogleAdsText


class GoogleAdsResearchAdGroup(GoogleAdsStrictModel):
    ad_group_id: str = Field(max_length=32)
    campaign_id: str = Field(max_length=32)
    name: GoogleAdsText
    # False when Google couldn't place keywords in it, such as a non-Search ad group.
    usable: bool


class GoogleAdsKeywordIdea(GoogleAdsStrictModel):
    # The keyword text google_ads_create_ad_groups and google_ads_create_keywords take.
    text: str = Field(min_length=1, max_length=200)
    # True for a keyword the agent asked metrics for, false for one of Google's ideas.
    requested: bool
    avg_monthly_searches: int | None = Field(default=None, ge=0)
    competition: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    # Top-of-page bid range in the account currency, as decimal strings.
    low_bid: GoogleAdsMoney | None = None
    high_bid: GoogleAdsMoney | None = None
    # Searches per month for the last 12 months, oldest first.
    trend: list[int] = Field(default_factory=list, max_length=48)
    themes: list[GoogleAdsText] = Field(default_factory=list, max_length=MAX_THEMES_PER_KEYWORD)
    close_variants: list[GoogleAdsText] = Field(default_factory=list, max_length=MAX_CLOSE_VARIANTS)
    # Set when the agent passed ad groups: where Google would put this keyword.
    ad_group_id: str | None = Field(default=None, max_length=32)
    match_type: Literal["EXACT", "PHRASE", "BROAD"] | None = None


class GoogleAdsKeywordResearchData(GoogleAdsStrictModel):
    account_id: str = Field(max_length=32)
    currency: str = Field(max_length=3)
    # Empty means every location.
    locations: list[GoogleAdsResearchPlace] = Field(max_length=MAX_RESEARCH_LOCATIONS)
    # None means every language.
    language: GoogleAdsResearchPlace | None
    ideas: list[GoogleAdsKeywordIdea] = Field(max_length=MAX_RESEARCH_ROWS)
    # Google's count of ideas for the seeds, which can exceed the rows returned.
    total_ideas: int = Field(ge=0)
    truncated: bool
    ad_groups: list[GoogleAdsResearchAdGroup] = Field(max_length=MAX_RESEARCH_AD_GROUPS)


class GoogleAdsKeywordResearchEntry(IntegrationFanOutEntry):
    data: GoogleAdsKeywordResearchData | None = None


class GoogleAdsKeywordResearchOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsKeywordResearchEntry]
