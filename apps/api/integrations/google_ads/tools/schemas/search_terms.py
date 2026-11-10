# apps/api/integrations/google_ads/tools/schemas/search_terms.py

"""Arguments and result contract for acting on Google Ads search terms."""

from datetime import date, timedelta
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.negative_keyword_criteria import negative_key
from ...operations.read_search_terms import keyword_key
from ...references import GoogleAdsAdGroupReference, GoogleAdsSharedSetReference
from .base import GoogleAdsStrictModel
from .negative_keywords import GoogleAdsMatchType

MAX_SEARCH_TERM_DECISIONS = 1_000
_MAX_DAYS = 366

type GoogleAdsSearchTermAction = Literal["add_negative", "add_keyword"]
type GoogleAdsNegativeLevel = Literal["ad_group", "campaign", "list"]


def _ad_group_name(reference: GoogleAdsAdGroupReference) -> str:
    return f"customers/{reference.customer_id}/adGroups/{reference.ad_group_id}"


class GoogleAdsSearchTermDecision(GoogleAdsStrictModel):
    """What to do with one search term, in the ad group it matched in."""

    search_term: str = Field(min_length=1, max_length=80)
    ad_group: GoogleAdsAdGroupReference = Field(description="The ad group the term matched in.")
    action: GoogleAdsSearchTermAction
    match_type: GoogleAdsMatchType
    level: GoogleAdsNegativeLevel | None = Field(
        default=None,
        description="For add_negative: block in the matched ad group, its campaign, or a list.",
    )
    negative_list: GoogleAdsSharedSetReference | None = Field(
        default=None, description="The negative keyword list, when level is list."
    )
    keyword_ad_group: GoogleAdsAdGroupReference | None = Field(
        default=None,
        description="For add_keyword: another ad group to add it to. Default: the matched one.",
    )

    @field_validator("search_term", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("search_term")
    @classmethod
    def _ten_words(cls, value: str) -> str:
        if len(value.split()) > 10:
            raise ValueError("A keyword can have at most 10 words, so this term can't be used.")
        return value

    @model_validator(mode="after")
    def _fits_action(self) -> Self:
        if self.action == "add_negative":
            if self.level is None or self.keyword_ad_group is not None:
                raise ValueError("A negative needs a level and no keyword_ad_group.")
            if (self.level == "list") != (self.negative_list is not None):
                raise ValueError("Give negative_list exactly when level is list.")
        elif self.level is not None or self.negative_list is not None:
            raise ValueError("A keyword takes keyword_ad_group, not a level or negative_list.")
        others = [item for item in (self.negative_list, self.keyword_ad_group) if item is not None]
        if any(item.customer_id != self.ad_group.customer_id for item in others):
            raise ValueError("Act on a search term only in the account it matched in.")
        return self

    @property
    def customer_id(self) -> str:
        return self.ad_group.customer_id

    @property
    def matched_in(self) -> str:
        return _ad_group_name(self.ad_group)

    @property
    def key(self) -> str:
        """Names the decision on the card: the term, where it matched, and the action."""
        # Lower case, as the card writes it; case folding would turn "ß" into "ss".
        term = " ".join(self.search_term.lower().split())
        return f"{self.matched_in}/{self.action}/{term}"

    @property
    def target(self) -> str:
        """The resource name of the campaign, ad group, or list that gets the criterion."""
        if self.action == "add_keyword":
            return _ad_group_name(self.keyword_ad_group or self.ad_group)
        if self.level == "campaign":
            return f"customers/{self.customer_id}/campaigns/{self.ad_group.campaign_id}"
        if self.level == "list" and self.negative_list is not None:
            return f"customers/{self.customer_id}/sharedSets/{self.negative_list.shared_set_id}"
        return self.matched_in

    @property
    def write_key(self) -> str:
        """Names the criterion this decision creates, the same way the reads name it."""
        if self.action == "add_keyword":
            return keyword_key(self.target, self.search_term, self.match_type)
        return negative_key(self.target, self.search_term, self.match_type)

    @property
    def target_kind(self) -> GoogleAdsNegativeLevel:
        return self.level or "ad_group"


class GoogleAdsOptimiseSearchTermsRequest(GoogleAdsStrictModel):
    """Every argument of a search terms change, so an edited approval is checked whole."""

    start_date: date
    end_date: date
    decisions: list[GoogleAdsSearchTermDecision] = Field(
        min_length=1, max_length=MAX_SEARCH_TERM_DECISIONS
    )

    @model_validator(mode="after")
    def _within_limits(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        if self.end_date - self.start_date > timedelta(days=_MAX_DAYS):
            raise ValueError("Read search terms over at most a year.")
        keys = [decision.key for decision in self.decisions]
        if len(set(keys)) != len(keys):
            raise ValueError("List each search term once per ad group and action.")
        writes = [decision.write_key for decision in self.decisions]
        if len(set(writes)) != len(writes):
            raise ValueError(
                "Two decisions add the same keyword or negative to the same place. Keep one."
            )
        return self


class GoogleAdsSearchTermOutcome(GoogleAdsStrictModel):
    search_term: str
    action: GoogleAdsSearchTermAction
    match_type: GoogleAdsMatchType
    target_kind: GoogleAdsNegativeLevel
    target_name: str
    campaign_name: str
    ad_group_name: str
    # Read from Google for the request's date range, never from the agent.
    clicks: int | None = None
    cost: str | None = None
    conversions: float | None = None
    outcome: Literal["added", "already_set", "failed", "unverified"]
    error_code: str | None = None
    message: str | None = None


class GoogleAdsSearchTermCounts(GoogleAdsStrictModel):
    negatives_added: int = Field(ge=0)
    keywords_added: int = Field(ge=0)
    already_set: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsOptimiseSearchTermsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    counts: GoogleAdsSearchTermCounts
    # Every decision on the card; the agent gets only the ones that didn't happen.
    outcomes: list[GoogleAdsSearchTermOutcome] = Field(max_length=MAX_SEARCH_TERM_DECISIONS)
    outcomes_truncated: bool = False


class GoogleAdsOptimiseSearchTermsEntry(IntegrationFanOutEntry):
    data: GoogleAdsOptimiseSearchTermsData | None = None


class GoogleAdsOptimiseSearchTermsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsOptimiseSearchTermsEntry]
