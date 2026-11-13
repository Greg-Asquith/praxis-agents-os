# apps/api/integrations/google_ads/tools/schemas/budget_updates.py

"""Arguments and result contract for changing Google Ads campaign budgets."""

from typing import Any, Literal, Self, cast

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.budget_settings import ACCOUNT_DEFAULT, network_code, network_setting
from ...operations.campaign_bidding import money
from ...references import GoogleAdsCampaignBudgetReference, GoogleAdsCampaignReference
from ..utils.money import money_to_micros
from .base import GoogleAdsStrictModel
from .campaign_budgets import GoogleAdsMoneyAmount

MAX_BUDGET_UPDATES = 100

type BudgetSetting = Literal["amount", "delivery", "shared_budget", "network_priority"]
type NetworkChannel = Literal["OWNED_AND_OPERATED", "SEARCH_PARTNER", "GOOGLE_DISPLAY"]


class GoogleAdsNetworkShare(GoogleAdsStrictModel):
    """A network that spends after the first ones, and the most of the budget it may take."""

    network: NetworkChannel
    # A whole percentage of the budget; 0 keeps the network from spending, and None sets no cap.
    cap_percent: int | None = Field(default=None, ge=0, le=100)


class GoogleAdsNetworkPriority(GoogleAdsStrictModel):
    """Which networks a budget spends on first, and which get what is left."""

    first: list[NetworkChannel] = Field(
        min_length=1, max_length=3, description="The networks that spend first."
    )
    then: list[GoogleAdsNetworkShare] = Field(
        default_factory=list,
        max_length=2,
        description=(
            "Every other network the campaign type can show on. Google refuses an order that "
            "leaves one out of both lists."
        ),
    )

    @model_validator(mode="after")
    def _each_network_once(self) -> Self:
        networks = [*self.first, *(share.network for share in self.then)]
        if len(set(networks)) != len(networks):
            raise ValueError("Put each network either first or after, once.")
        return self

    def setting(self, channel_type: str) -> dict[str, Any]:
        """The order as Google stores it for one campaign type."""
        return network_setting(
            channel_type, self.first, [(share.network, share.cap_percent) for share in self.then]
        )


class GoogleAdsBudgetUpdate(GoogleAdsStrictModel):
    """One campaign or budget and how its budget changes."""

    campaign: GoogleAdsCampaignReference | None = None
    budget: GoogleAdsCampaignBudgetReference | None = None
    # The new daily amount, on the campaign's budget or the named budget.
    amount: GoogleAdsMoneyAmount | None = None
    delivery: Literal["STANDARD", "ACCELERATED"] | None = None
    # Moves the campaign onto this shared budget.
    use_shared_budget: GoogleAdsCampaignBudgetReference | None = None
    # The networks the budget spends on first; `account_default` takes the budget's own order off.
    network_priority: GoogleAdsNetworkPriority | Literal["account_default"] | None = None

    @model_validator(mode="after")
    def _one_target_and_a_change(self) -> Self:
        if (self.campaign is None) == (self.budget is None):
            raise ValueError("Name either a campaign or a budget in each budget change.")
        if not self.requested:
            raise ValueError(f"Name at least one budget change for {self.label}.")
        if self.use_shared_budget is not None:
            if self.campaign is None:
                raise ValueError("Only a campaign can move onto a shared budget.")
            if not {"amount", "delivery", "network_priority"}.isdisjoint(self.requested):
                raise ValueError(
                    f"Move {self.label} onto the shared budget in one change, and change the "
                    "shared budget's settings in another."
                )
            if self.use_shared_budget.customer_id != self.campaign.customer_id:
                raise ValueError(
                    f"{self.label} can only use a shared budget from its own Google Ads account."
                )
        return self

    @property
    def reference(self) -> GoogleAdsCampaignReference | GoogleAdsCampaignBudgetReference:
        return self.campaign or cast(GoogleAdsCampaignBudgetReference, self.budget)

    @property
    def customer_id(self) -> str:
        return self.reference.customer_id

    @property
    def label(self) -> str:
        return self.reference.label

    @property
    def resource_name(self) -> str:
        if self.campaign is not None:
            return f"customers/{self.customer_id}/campaigns/{self.campaign.campaign_id}"
        return f"customers/{self.customer_id}/campaignBudgets/{self.reference.provider_entity_id}"

    @property
    def shared_budget_name(self) -> str | None:
        target = self.use_shared_budget
        return (
            None
            if target is None
            else f"customers/{target.customer_id}/campaignBudgets/{target.budget_id}"
        )

    @property
    def requested(self) -> dict[BudgetSetting, Any]:
        """The settings that change, in card terms: money as a canonical decimal."""
        values: dict[BudgetSetting, Any] = {}
        if self.amount is not None:
            values["amount"] = money(money_to_micros(self.amount))
        if self.delivery is not None:
            values["delivery"] = self.delivery
        if self.shared_budget_name is not None:
            values["shared_budget"] = self.shared_budget_name
        if isinstance(self.network_priority, GoogleAdsNetworkPriority):
            values["network_priority"] = network_code(self.network_priority.setting(""))
        elif self.network_priority is not None:
            values["network_priority"] = ACCOUNT_DEFAULT
        return values


class GoogleAdsUpdateBudgetsRequest(GoogleAdsStrictModel):
    """Every argument of a budget update, so an edited approval is checked whole."""

    changes: list[GoogleAdsBudgetUpdate] = Field(min_length=1, max_length=MAX_BUDGET_UPDATES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [change.resource_name for change in self.changes]
        if len(set(names)) != len(names):
            raise ValueError("List each campaign and budget once, with all of its changes.")
        return self


class GoogleAdsBudgetSettingOutcome(GoogleAdsStrictModel):
    setting: BudgetSetting
    # As the approval card showed it; a shared budget is shown by name, and a network order as
    # tiers of networks, such as `OWNED_AND_OPERATED>SEARCH_PARTNER:20` for a 20% cap.
    before: str | None
    requested: str | None
    # Read back after the change; meaningful only when the row's `read_back` is true.
    after: str | None
    outcome: Literal["updated", "already_set", "failed", "unverified"]


class GoogleAdsBudgetUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    kind: Literal["campaign", "budget"]
    name: str
    budget_name: str
    shared: bool
    # This month's cost for the budget, or for the campaign when it moves, as the card showed it.
    spend_this_month: str | None = None
    read_back: bool
    settings: list[GoogleAdsBudgetSettingOutcome] = Field(max_length=4)
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateBudgetsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    budgets: list[GoogleAdsBudgetUpdateOutcome] = Field(max_length=MAX_BUDGET_UPDATES)


class GoogleAdsUpdateBudgetsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateBudgetsData | None = None


class GoogleAdsUpdateBudgetsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateBudgetsEntry]
