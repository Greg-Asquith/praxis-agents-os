# apps/api/integrations/google_ads/tools/schemas/campaign_updates.py

"""Arguments and result contract for changing the settings of live Google Ads campaigns."""

from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.campaign_bidding import Bidding, money
from ...operations.campaign_goals import ACCOUNT_GOALS
from ...operations.campaign_settings import CampaignSetting
from ...references import GoogleAdsBiddingStrategyReference, GoogleAdsCampaignReference
from ..utils.money import money_to_micros
from .base import GoogleAdsStrictModel
from .campaigns import (
    GoogleAdsCampaignGoal,
    GoogleAdsManualCpc,
    GoogleAdsMaxCpc,
    GoogleAdsMaximizeClicks,
    GoogleAdsMaximizeConversions,
    GoogleAdsMaximizeConversionValue,
    GoogleAdsTargetCpa,
    GoogleAdsTargetImpressionShare,
)
from .performance_max import GoogleAdsVideoPages
from .url_options import GoogleAdsUrlOptions, GoogleAdsUrlParameter

MAX_CAMPAIGN_UPDATES = 50


class GoogleAdsCampaignNetworks(GoogleAdsStrictModel):
    search_partners: bool | None = None
    display_expansion: bool | None = None


class GoogleAdsPortfolioBidding(GoogleAdsStrictModel):
    """Moves the campaign onto a portfolio strategy in the same account."""

    strategy: Literal["PORTFOLIO"]
    portfolio: GoogleAdsBiddingStrategyReference


class GoogleAdsBiddingTargets(GoogleAdsStrictModel):
    """Changes only targets on the campaign's current standard strategy."""

    strategy: Literal["TARGETS"]
    target_cpa: GoogleAdsTargetCpa | None = None
    # A ratio, so 3.5 means 350%.
    target_roas: float | None = Field(default=None, ge=0.01, le=1000)
    max_cpc: GoogleAdsMaxCpc | None = None

    @model_validator(mode="after")
    def _names_a_target(self) -> Self:
        if self.target_cpa is None and self.target_roas is None and self.max_cpc is None:
            raise ValueError("Name target_cpa, target_roas, or max_cpc to change.")
        return self


type GoogleAdsCampaignBidding = Annotated[
    GoogleAdsManualCpc
    | GoogleAdsMaximizeClicks
    | GoogleAdsMaximizeConversions
    | GoogleAdsMaximizeConversionValue
    | GoogleAdsTargetImpressionShare
    | GoogleAdsPortfolioBidding
    | GoogleAdsBiddingTargets,
    Field(discriminator="strategy"),
]


def card_request(bidding: GoogleAdsCampaignBidding) -> Bidding:
    """A bidding request in card terms, with money as canonical decimal strings."""
    if isinstance(bidding, GoogleAdsPortfolioBidding):
        return {"strategy": "PORTFOLIO", "portfolio": bidding.portfolio.resource_name}
    fields = bidding.model_dump(exclude_none=isinstance(bidding, GoogleAdsBiddingTargets))
    for key in ("target_cpa", "max_cpc"):
        if fields.get(key):
            fields[key] = money(money_to_micros(fields[key]))
    return fields


class GoogleAdsCampaignUpdate(GoogleAdsStrictModel):
    """One campaign and only the settings that change."""

    campaign: GoogleAdsCampaignReference
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Dates in the account time zone.
    start_date: date | None = None
    # "none" runs the campaign with no end date.
    end_date: date | Literal["none"] | None = None
    url_options: GoogleAdsUrlOptions | None = None
    networks: GoogleAdsCampaignNetworks | None = None
    # Replaces the pages Google may take videos from; an empty list turns video crawl off.
    video_pages: GoogleAdsVideoPages | None = None
    # Performance Max only. Google customises text whenever final URL expansion is on.
    final_url_expansion: bool | None = None
    text_customisation: bool | None = None
    # "account" bids for the account's goals; a list bids for exactly those in this campaign.
    conversion_goals: list[GoogleAdsCampaignGoal] | Literal["account"] | None = Field(
        default=None, max_length=100
    )
    bidding: GoogleAdsCampaignBidding | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        # Google refuses line breaks in names.
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if not self.requested:
            raise ValueError(
                f"Name at least one setting to change for campaign {self.campaign.label}."
            )
        start, end = self.start_date, self.end_date
        if isinstance(start, date) and isinstance(end, date) and end < start:
            raise ValueError("The end date must be on or after the start date.")
        if (
            isinstance(self.bidding, GoogleAdsPortfolioBidding)
            and self.bidding.portfolio.customer_id != self.campaign.customer_id
        ):
            raise ValueError("Choose a portfolio strategy from the campaign's own account.")
        if isinstance(self.conversion_goals, list):
            goals = {(goal.category, goal.origin) for goal in self.conversion_goals}
            if not goals:
                raise ValueError("Choose at least one conversion goal, or use the account's goals.")
            if len(goals) != len(self.conversion_goals):
                raise ValueError("List each conversion goal once.")
        return self

    @property
    def resource_name(self) -> str:
        return f"customers/{self.campaign.customer_id}/campaigns/{self.campaign.campaign_id}"

    @property
    def requested(self) -> dict[CampaignSetting, Any]:
        """The settings that change, in card terms.

        Dates are `YYYY-MM-DD`, no end date is null, and goals are in category and origin order.
        """
        values: dict[CampaignSetting, Any] = {}
        if self.name is not None:
            values["name"] = self.name
        if self.start_date is not None:
            values["start_date"] = self.start_date.isoformat()
        if self.end_date is not None:
            values["end_date"] = None if self.end_date == "none" else self.end_date.isoformat()
        if self.url_options is not None:
            values.update(self.url_options.requested)
        networks = self.networks
        if networks is not None:
            if networks.search_partners is not None:
                values["search_partners"] = networks.search_partners
            if networks.display_expansion is not None:
                values["display_expansion"] = networks.display_expansion
        if self.video_pages is not None:
            values["video_pages"] = list(self.video_pages)
        if self.final_url_expansion is not None:
            values["final_url_expansion"] = self.final_url_expansion
        if self.text_customisation is not None:
            values["text_customisation"] = self.text_customisation
        if isinstance(self.conversion_goals, list):
            values["conversion_goals"] = sorted(
                (goal.model_dump() for goal in self.conversion_goals),
                key=lambda goal: (goal["category"], goal["origin"]),
            )
        elif self.conversion_goals is not None:
            values["conversion_goals"] = ACCOUNT_GOALS
        if self.bidding is not None:
            values["bidding"] = card_request(self.bidding)
        return values


class GoogleAdsUpdateCampaignsRequest(GoogleAdsStrictModel):
    """Every argument of a campaign update, so an edited approval is checked whole."""

    changes: list[GoogleAdsCampaignUpdate] = Field(min_length=1, max_length=MAX_CAMPAIGN_UPDATES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [change.resource_name for change in self.changes]
        if len(set(names)) != len(names):
            raise ValueError("List each campaign once, with all of its changes.")
        return self


class GoogleAdsBiddingValue(GoogleAdsStrictModel):
    """Bidding in card terms; only the strategy's own fields are set."""

    strategy: str = Field(max_length=64)
    target_cpa: str | None = Field(default=None, max_length=32)
    target_roas: float | None = None
    max_cpc: str | None = Field(default=None, max_length=32)
    location: str | None = Field(default=None, max_length=64)
    share_percent: int | None = None
    portfolio: str | None = Field(default=None, max_length=200)
    # Google's strategy type when the card has no name for it.
    type: str | None = Field(default=None, max_length=64)


# Conversion goals are "account", "custom", or the goals that bid.
type GoogleAdsSettingValue = (
    str
    | bool
    | list[GoogleAdsUrlParameter]
    | list[GoogleAdsCampaignGoal]
    | list[str]
    | GoogleAdsBiddingValue
    | None
)


class GoogleAdsCampaignSettingOutcome(GoogleAdsStrictModel):
    setting: CampaignSetting
    # As the approval card showed it.
    before: GoogleAdsSettingValue
    requested: GoogleAdsSettingValue
    # Read back after the change; meaningful only when the campaign's `read_back` is true.
    after: GoogleAdsSettingValue
    outcome: Literal["updated", "already_set", "failed", "unverified"]


class GoogleAdsCampaignUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    campaign_id: str
    name: str
    read_back: bool
    settings: list[GoogleAdsCampaignSettingOutcome] = Field(max_length=16)
    error_code: str | None = None
    message: str | None = None


class GoogleAdsPortfolioName(GoogleAdsStrictModel):
    resource_name: str = Field(max_length=200)
    name: str = Field(max_length=255)


class GoogleAdsUpdateCampaignsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    # Names of the portfolio strategies that bidding values name.
    portfolios: list[GoogleAdsPortfolioName] = Field(
        default_factory=list, max_length=2 * MAX_CAMPAIGN_UPDATES
    )
    campaigns: list[GoogleAdsCampaignUpdateOutcome] = Field(max_length=MAX_CAMPAIGN_UPDATES)


class GoogleAdsUpdateCampaignsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateCampaignsData | None = None


class GoogleAdsUpdateCampaignsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateCampaignsEntry]
