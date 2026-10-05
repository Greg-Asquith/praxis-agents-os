# apps/api/integrations/meta_ads/tools/schemas/budgets.py

"""Input and result contracts for changing Meta campaign and ad set budgets."""

import re
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsMoney, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdSetReference, MetaAdsCampaignReference


def _positive(value: str) -> str:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value) or Decimal(value) <= 0:
        raise ValueError("Set a budget above zero, with at most two decimal places.")
    return value


type MetaAdsBudgetAmount = Annotated[
    str,
    AfterValidator(_positive),
    Field(
        max_length=32,
        description=(
            "New positive amount in the ad account currency, for example 25.50. "
            "Use currency units, not cents."
        ),
    ),
]


class MetaAdsBudgetUpdate(MetaAdsStrictModel):
    """One new budget amount for either a campaign or an ad set."""

    campaign: MetaAdsCampaignReference | None = Field(
        default=None, description="Campaign whose own budget changes."
    )
    ad_set: MetaAdsAdSetReference | None = Field(
        default=None, description="Ad set whose own budget changes."
    )
    amount: MetaAdsBudgetAmount

    @model_validator(mode="after")
    def _check_target(self) -> Self:
        if (self.campaign is None) == (self.ad_set is None):
            raise ValueError("Set exactly one of campaign or ad_set.")
        return self

    @property
    def reference(self) -> MetaAdsCampaignReference | MetaAdsAdSetReference:
        reference = self.campaign or self.ad_set
        if reference is None:
            raise ValueError("Meta Ads budget update has no reference")
        return reference


class MetaAdsBudgetOutcome(MetaAdsStrictModel):
    object_type: Literal["campaign", "adset"]
    object_id: MetaAdsId
    object_name: MetaAdsText | None
    budget_kind: Literal["daily", "lifetime"]
    previous_amount: MetaAdsMoney
    requested_amount: MetaAdsMoney
    # Read back after the change; null when the budget couldn't be read.
    amount: MetaAdsMoney | None
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsBudgetData(MetaAdsStrictModel):
    account_id: MetaAdsId
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    budgets: list[MetaAdsBudgetOutcome] = Field(max_length=50)


class MetaAdsBudgetEntry(IntegrationFanOutEntry):
    data: MetaAdsBudgetData | None = None


class MetaAdsBudgetOutput(IntegrationFanOutOutput):
    results: list[MetaAdsBudgetEntry]
