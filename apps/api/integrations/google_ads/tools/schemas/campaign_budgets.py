# apps/api/integrations/google_ads/tools/schemas/campaign_budgets.py

"""Input and result contracts for Google Ads campaign budget actions."""

from typing import Literal

from pydantic import Field

from integrations.google_ads.references import (
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
)
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleAdsStrictModel


class GoogleAdsDailyBudgetAmount(GoogleAdsStrictModel):
    daily_amount: str = Field(
        min_length=1,
        max_length=32,
        description=(
            "Positive decimal amount in the Google Ads account currency, with up to six "
            "decimal places. Use currency units, not micros."
        ),
    )


class GoogleAdsTotalBudgetAmount(GoogleAdsStrictModel):
    total_amount: str = Field(
        min_length=1,
        max_length=32,
        description=(
            "Positive decimal amount in the Google Ads account currency, with up to six "
            "decimal places. Use currency units, not micros."
        ),
    )


type GoogleAdsCampaignBudgetAmount = GoogleAdsDailyBudgetAmount | GoogleAdsTotalBudgetAmount


class GoogleAdsCampaignBudgetAmountUpdate(GoogleAdsStrictModel):
    budget: GoogleAdsCampaignBudgetReference
    amount: str = Field(
        min_length=1,
        max_length=32,
        description=(
            "Positive decimal amount in the Google Ads account currency, with up to six "
            "decimal places. Use currency units, not micros."
        ),
    )


class GoogleAdsCreateCampaignBudgetData(GoogleAdsStrictModel):
    name: str
    period: Literal["DAILY", "CUSTOM_PERIOD"]
    amount: str
    amount_micros: int
    currency_code: str
    delivery_method: Literal["STANDARD", "ACCELERATED"]
    explicitly_shared: bool
    outcome: Literal["created", "failed", "unverified"]
    reference: GoogleAdsCampaignBudgetReference | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCreateCampaignBudgetEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateCampaignBudgetData | None = None


class GoogleAdsCreateCampaignBudgetOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateCampaignBudgetEntry]


class GoogleAdsCampaignBudgetAmountOutcome(GoogleAdsStrictModel):
    reference: GoogleAdsCampaignBudgetReference
    previous_amount: str
    requested_amount: str
    previous_amount_micros: int
    requested_amount_micros: int
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    campaign_label_count: int = Field(ge=0)
    campaign_labels_truncated: bool
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCampaignBudgetAmountCounts(GoogleAdsStrictModel):
    updated: int = Field(ge=0)
    already_set: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsCampaignBudgetAmountSamples(GoogleAdsStrictModel):
    updated: list[GoogleAdsCampaignBudgetAmountOutcome]
    already_set: list[GoogleAdsCampaignBudgetAmountOutcome]
    failed: list[GoogleAdsCampaignBudgetAmountOutcome]
    unverified: list[GoogleAdsCampaignBudgetAmountOutcome]


class GoogleAdsUpdateCampaignBudgetAmountsData(GoogleAdsStrictModel):
    counts: GoogleAdsCampaignBudgetAmountCounts
    samples: GoogleAdsCampaignBudgetAmountSamples
    samples_truncated: bool
    campaign_labels_truncated: bool
    audit_note: str | None = None


class GoogleAdsUpdateCampaignBudgetAmountsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateCampaignBudgetAmountsData | None = None


class GoogleAdsUpdateCampaignBudgetAmountsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateCampaignBudgetAmountsEntry]


class GoogleAdsCampaignBudgetAssignmentOutcome(GoogleAdsStrictModel):
    campaign: GoogleAdsCampaignReference
    previous_budget: GoogleAdsCampaignBudgetReference
    requested_budget: GoogleAdsCampaignBudgetReference
    outcome: Literal["assigned", "already_set", "failed", "unverified"]
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCampaignBudgetAssignmentCounts(GoogleAdsStrictModel):
    assigned: int = Field(ge=0)
    already_set: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsCampaignBudgetAssignmentSamples(GoogleAdsStrictModel):
    assigned: list[GoogleAdsCampaignBudgetAssignmentOutcome]
    already_set: list[GoogleAdsCampaignBudgetAssignmentOutcome]
    failed: list[GoogleAdsCampaignBudgetAssignmentOutcome]
    unverified: list[GoogleAdsCampaignBudgetAssignmentOutcome]


class GoogleAdsAssignCampaignBudgetsData(GoogleAdsStrictModel):
    destination_budget: GoogleAdsCampaignBudgetReference
    counts: GoogleAdsCampaignBudgetAssignmentCounts
    samples: GoogleAdsCampaignBudgetAssignmentSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsAssignCampaignBudgetsEntry(IntegrationFanOutEntry):
    data: GoogleAdsAssignCampaignBudgetsData | None = None


class GoogleAdsAssignCampaignBudgetsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAssignCampaignBudgetsEntry]


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
