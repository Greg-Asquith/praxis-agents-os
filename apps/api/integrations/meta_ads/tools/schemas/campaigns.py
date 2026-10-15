# apps/api/integrations/meta_ads/tools/schemas/campaigns.py

"""Input and result contracts for creating one paused campaign in an ad account."""

from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...operations.targeting import MetaAdsCountryCode
from ...references import MetaAdsCampaignReference
from .budgets import MetaAdsBidStrategy, MetaAdsBudgetAmount

MAX_CAMPAIGN_NAME = 400

type MetaAdsObjective = Literal[
    "sales", "leads", "traffic", "engagement", "awareness", "app_promotion"
]
OBJECTIVES: dict[MetaAdsObjective, str] = {
    "sales": "OUTCOME_SALES",
    "leads": "OUTCOME_LEADS",
    "traffic": "OUTCOME_TRAFFIC",
    "engagement": "OUTCOME_ENGAGEMENT",
    "awareness": "OUTCOME_AWARENESS",
    "app_promotion": "OUTCOME_APP_PROMOTION",
}
# Politics is listed so it can be refused with a reason rather than as an unknown value.
type MetaAdsSpecialCategory = Literal[
    "housing",
    "employment",
    "financial_products_services",
    "online_gambling_and_gaming",
    "issues_elections_politics",
]
type MetaAdsCampaignBudgetMode = Literal["campaign_daily", "campaign_lifetime", "ad_set"]
_POLITICS_REFUSED = (
    "Praxis can't create political, election, or social issue campaigns, because Meta needs a "
    "Page authorisation Praxis doesn't manage. Create this campaign in Ads Manager."
)


def _name(value: str) -> str:
    if not value.strip():
        raise ValueError("Write a campaign name.")
    return " ".join(value.split())


class MetaAdsCampaignBudget(MetaAdsStrictModel):
    mode: MetaAdsCampaignBudgetMode = "campaign_daily"
    amount: MetaAdsBudgetAmount | None = None
    # Lets ad sets share up to 20% of their budgets; only for ad_set mode.
    share_between_ad_sets: bool | None = None

    @model_validator(mode="after")
    def _fields_for_mode(self) -> Self:
        if self.mode == "ad_set":
            if self.amount is not None:
                raise ValueError("With ad_set budgets, set the amount on each ad set instead.")
            if self.share_between_ad_sets is None:
                raise ValueError("With ad_set budgets, set share_between_ad_sets.")
        else:
            if self.amount is None:
                raise ValueError("A campaign budget needs an amount.")
            if self.share_between_ad_sets is not None:
                raise ValueError("Only ad_set budgets take share_between_ad_sets.")
        return self


class MetaAdsSpecialAdCategory(MetaAdsStrictModel):
    category: MetaAdsSpecialCategory
    countries: list[MetaAdsCountryCode] = Field(min_length=1, max_length=50)


class MetaAdsCreateCampaignRequest(MetaAdsStrictModel):
    name: Annotated[str, Field(max_length=MAX_CAMPAIGN_NAME), AfterValidator(_name)]
    objective: MetaAdsObjective
    budget: MetaAdsCampaignBudget
    bid_strategy: MetaAdsBidStrategy = "highest_volume"
    special_ad_categories: list[MetaAdsSpecialAdCategory] = Field(
        default_factory=list, max_length=4
    )
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    spend_limit: MetaAdsBudgetAmount | None = None

    @model_validator(mode="after")
    def _check_request(self) -> Self:
        if problems := _request_problems(self):
            raise ValueError(problems[0])
        return self


def _request_problems(request: MetaAdsCreateCampaignRequest) -> list[str]:
    categories = [item.category for item in request.special_ad_categories]
    problems: list[str] = []
    if "issues_elections_politics" in categories:
        problems.append(_POLITICS_REFUSED)
    if len(set(categories)) != len(categories):
        problems.append("List each special ad category once.")
    if request.budget.mode == "campaign_lifetime" and not request.end_date:
        problems.append("A lifetime budget needs an end_date.")
    if request.bid_strategy == "roas_goal" and (
        request.objective != "sales" or request.budget.mode == "ad_set"
    ):
        problems.append("A return on ad spend goal needs a sales campaign with a campaign budget.")
    return problems


type MetaAdsCreatedCampaignOutcome = Literal["created", "failed", "unverified"]


class MetaAdsCreatedCampaign(MetaAdsStrictModel):
    name: MetaAdsText
    objective: MetaAdsObjective
    outcome: MetaAdsCreatedCampaignOutcome
    # True when an unclear reply was settled by finding the campaign by name.
    recovered: bool
    # False when the campaign couldn't be read back after it was made.
    verified: bool
    campaign_id: MetaAdsId | None
    effective_status: MetaAdsText | None
    # Read back from Meta, ready to pass to meta_ads_create_ad_set.
    campaign: MetaAdsCampaignReference | None
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsCreateCampaignData(MetaAdsStrictModel):
    account_id: MetaAdsId
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    campaign: MetaAdsCreatedCampaign


class MetaAdsCreateCampaignEntry(IntegrationFanOutEntry):
    data: MetaAdsCreateCampaignData | None = None


class MetaAdsCreateCampaignOutput(IntegrationFanOutOutput):
    results: list[MetaAdsCreateCampaignEntry]
