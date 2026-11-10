# apps/api/integrations/google_ads/tools/schemas/campaign_budgets.py

"""The budget amount type and the result contract for removing Google Ads campaign budgets."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from integrations.google_ads.references import GoogleAdsCampaignBudgetReference
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ..utils.money import money_to_micros
from .base import GoogleAdsStrictModel


def _valid_money_amount(value: str) -> str:
    money_to_micros(value, label="budget amount")
    return value


GoogleAdsMoneyAmount = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        description=(
            "Positive decimal amount in the Google Ads account currency, with up to six "
            "decimal places. Use currency units, not micros."
        ),
    ),
    AfterValidator(_valid_money_amount),
]


class GoogleAdsCampaignBudgetRemovalOutcome(GoogleAdsStrictModel):
    reference: GoogleAdsCampaignBudgetReference
    previous_status: str
    resulting_status: str | None = None
    outcome: Literal["removed", "failed", "unverified"]
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCampaignBudgetRemovalCounts(GoogleAdsStrictModel):
    removed: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsCampaignBudgetRemovalSamples(GoogleAdsStrictModel):
    removed: list[GoogleAdsCampaignBudgetRemovalOutcome]
    failed: list[GoogleAdsCampaignBudgetRemovalOutcome]
    unverified: list[GoogleAdsCampaignBudgetRemovalOutcome]


class GoogleAdsRemoveCampaignBudgetsData(GoogleAdsStrictModel):
    counts: GoogleAdsCampaignBudgetRemovalCounts
    samples: GoogleAdsCampaignBudgetRemovalSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsRemoveCampaignBudgetsEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemoveCampaignBudgetsData | None = None


class GoogleAdsRemoveCampaignBudgetsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemoveCampaignBudgetsEntry]
