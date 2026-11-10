# apps/api/integrations/google_ads/tools/schemas/negative_keywords.py

"""Arguments and result contract for adding and removing Google Ads negative keywords."""

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsSharedSetReference,
)
from .base import GoogleAdsStrictModel

MAX_NEGATIVE_KEYWORD_TARGETS = 100
MAX_NEGATIVE_KEYWORDS = 1_000
MAX_LIST_CAMPAIGN_CHANGES = 1_000
# One row per change, so the result holds every keyword and campaign link a call can make.
_MAX_OUTCOMES = MAX_NEGATIVE_KEYWORDS + MAX_LIST_CAMPAIGN_CHANGES + MAX_NEGATIVE_KEYWORD_TARGETS

type GoogleAdsMatchType = Literal["EXACT", "PHRASE", "BROAD"]
type GoogleAdsNegativeTargetKind = Literal["campaign", "ad_group", "list", "new_list"]


class NegativeKeywordEntry(GoogleAdsStrictModel):
    text: str = Field(min_length=1, max_length=80)
    match_type: GoogleAdsMatchType

    @field_validator("text", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("text")
    @classmethod
    def _ten_words(cls, value: str) -> str:
        if len(value.split()) > 10:
            raise ValueError("A negative keyword can have at most 10 words.")
        return value

    @property
    def pair(self) -> tuple[str, str]:
        return self.text.casefold(), self.match_type


class _NegativeKeywordChange(GoogleAdsStrictModel):
    add: list[NegativeKeywordEntry] = Field(default_factory=list)
    remove: list[NegativeKeywordEntry] = Field(default_factory=list)

    @property
    def customer_id(self) -> str:
        raise NotImplementedError

    @property
    def target_key(self) -> str:
        """The target's resource name, or a stand-in name for a list this call creates."""
        raise NotImplementedError

    @property
    def campaigns(self) -> list[GoogleAdsCampaignReference]:
        return []

    @property
    def keyword_count(self) -> int:
        return len(self.add) + len(self.remove)

    @model_validator(mode="after")
    def _each_keyword_once(self) -> Self:
        pairs = [keyword.pair for keyword in (*self.add, *self.remove)]
        if len(set(pairs)) != len(pairs):
            raise ValueError("List each keyword and match type once per target.")
        if not pairs and not self.campaigns:
            raise ValueError("Each target needs at least one keyword or campaign to change.")
        return self


class GoogleAdsCampaignNegatives(_NegativeKeywordChange):
    kind: Literal["campaign"]
    campaign: GoogleAdsCampaignReference

    @property
    def customer_id(self) -> str:
        return self.campaign.customer_id

    @property
    def target_key(self) -> str:
        return f"customers/{self.customer_id}/campaigns/{self.campaign.campaign_id}"


class GoogleAdsAdGroupNegatives(_NegativeKeywordChange):
    kind: Literal["ad_group"]
    ad_group: GoogleAdsAdGroupReference

    @property
    def customer_id(self) -> str:
        return self.ad_group.customer_id

    @property
    def target_key(self) -> str:
        return f"customers/{self.customer_id}/adGroups/{self.ad_group.ad_group_id}"


class GoogleAdsListNegatives(_NegativeKeywordChange):
    kind: Literal["list"]
    negative_list: GoogleAdsSharedSetReference
    apply_to_campaigns: list[GoogleAdsCampaignReference] = Field(default_factory=list)
    remove_from_campaigns: list[GoogleAdsCampaignReference] = Field(default_factory=list)

    @property
    def customer_id(self) -> str:
        return self.negative_list.customer_id

    @property
    def target_key(self) -> str:
        return f"customers/{self.customer_id}/sharedSets/{self.negative_list.shared_set_id}"

    @property
    def campaigns(self) -> list[GoogleAdsCampaignReference]:
        return [*self.apply_to_campaigns, *self.remove_from_campaigns]


class GoogleAdsNewListNegatives(GoogleAdsStrictModel):
    kind: Literal["new_list"]
    # The new list's name. It goes in the account of the campaigns that use it.
    new_list: str = Field(min_length=1, max_length=255)
    add: list[NegativeKeywordEntry] = Field(min_length=1)
    # A list only blocks searches once a campaign uses it.
    apply_to_campaigns: list[GoogleAdsCampaignReference] = Field(min_length=1)

    @field_validator("new_list", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @property
    def customer_id(self) -> str:
        return self.apply_to_campaigns[0].customer_id

    @property
    def target_key(self) -> str:
        return f"customers/{self.customer_id}/newSharedSets/{self.new_list.casefold()}"

    @property
    def campaigns(self) -> list[GoogleAdsCampaignReference]:
        return list(self.apply_to_campaigns)

    @property
    def remove(self) -> list[NegativeKeywordEntry]:
        return []

    @property
    def keyword_count(self) -> int:
        return len(self.add)

    @model_validator(mode="after")
    def _each_keyword_once(self) -> Self:
        pairs = [keyword.pair for keyword in self.add]
        if len(set(pairs)) != len(pairs):
            raise ValueError("List each keyword and match type once per target.")
        return self


# A plain alias, since the reference-type walker doesn't unwrap `type` statements.
GoogleAdsNegativeKeywordChange = Annotated[
    GoogleAdsCampaignNegatives
    | GoogleAdsAdGroupNegatives
    | GoogleAdsListNegatives
    | GoogleAdsNewListNegatives,
    Field(discriminator="kind"),
]


class GoogleAdsUpdateNegativeKeywordsRequest(GoogleAdsStrictModel):
    """Every argument of a negative keyword change, so an edited approval is checked whole."""

    entries: list[GoogleAdsNegativeKeywordChange] = Field(
        min_length=1, max_length=MAX_NEGATIVE_KEYWORD_TARGETS
    )

    @model_validator(mode="after")
    def _within_limits(self) -> Self:
        targets = [entry.target_key for entry in self.entries]
        if len(set(targets)) != len(targets):
            raise ValueError("List each campaign, ad group, and list once.")
        for entry in self.entries:
            campaigns = entry.campaigns
            if any(campaign.customer_id != entry.customer_id for campaign in campaigns):
                raise ValueError("A list can only be used by campaigns in its own account.")
            ids = [campaign.campaign_id for campaign in campaigns]
            if len(set(ids)) != len(ids):
                raise ValueError("List each campaign once per list.")
        if sum(entry.keyword_count for entry in self.entries) > MAX_NEGATIVE_KEYWORDS:
            raise ValueError(
                f"One request can add or remove at most {MAX_NEGATIVE_KEYWORDS:,} negative "
                "keywords."
            )
        if sum(len(entry.campaigns) for entry in self.entries) > MAX_LIST_CAMPAIGN_CHANGES:
            raise ValueError(
                f"One request can change at most {MAX_LIST_CAMPAIGN_CHANGES:,} campaign lists."
            )
        return self


class GoogleAdsNegativeKeywordOutcome(GoogleAdsStrictModel):
    target_kind: GoogleAdsNegativeTargetKind
    target_name: str
    # `keyword` is a negative keyword; `campaign` is a list's use by a campaign.
    item: Literal["keyword", "campaign", "list"]
    action: Literal["add", "remove", "create"]
    # The keyword text, the campaign's name, or the new list's name.
    name: str
    match_type: GoogleAdsMatchType | None = None
    outcome: Literal[
        "added", "removed", "created", "already_set", "not_found", "failed", "unverified"
    ]
    error_code: str | None = None
    message: str | None = None


class GoogleAdsNegativeKeywordCounts(GoogleAdsStrictModel):
    added: int = Field(ge=0)
    removed: int = Field(ge=0)
    created: int = Field(ge=0)
    already_set: int = Field(ge=0)
    not_found: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsUpdateNegativeKeywordsData(GoogleAdsStrictModel):
    account_id: str
    counts: GoogleAdsNegativeKeywordCounts
    # Every change on the card; the agent gets only the ones that didn't happen.
    outcomes: list[GoogleAdsNegativeKeywordOutcome] = Field(max_length=_MAX_OUTCOMES)
    outcomes_truncated: bool = False


class GoogleAdsUpdateNegativeKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateNegativeKeywordsData | None = None


class GoogleAdsUpdateNegativeKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateNegativeKeywordsEntry]
