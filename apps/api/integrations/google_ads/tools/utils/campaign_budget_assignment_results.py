# apps/api/integrations/google_ads/tools/utils/campaign_budget_assignment_results.py

"""Bounded Google Ads campaign budget assignment results."""

from collections.abc import Mapping
from typing import Any, Literal

from integrations.google_ads.references import (
    GoogleAdsCampaignBudgetReference,
    GoogleAdsCampaignReference,
)

from .bounded_outcome_results import bounded_outcome_result

type CampaignBudgetAssignmentOutcome = Literal["assigned", "already_set", "failed", "unverified"]

MAX_CAMPAIGN_BUDGET_ASSIGNMENT_RESULT_CHARS = 12_000
MAX_CAMPAIGN_BUDGET_ASSIGNMENT_DISPLAY_DATA_CHARS = 250_000
MAX_CAMPAIGN_BUDGET_ASSIGNMENT_PUBLIC_RESULT_CHARS = 1_000_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_AUDIT_NOTE = "Complete bounded assignment evidence is retained in the audit trail."
_OUTCOMES: tuple[CampaignBudgetAssignmentOutcome, ...] = (
    "assigned",
    "already_set",
    "failed",
    "unverified",
)


def bounded_campaign_budget_assignment_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Returns exact counts and representative assignment rows for model context."""
    return _bounded_result(
        result,
        max_chars=MAX_CAMPAIGN_BUDGET_ASSIGNMENT_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        audit_note=_AUDIT_NOTE,
    )


def display_campaign_budget_assignment_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Returns every assignment row that fits the application display budget."""
    return _bounded_result(
        result,
        max_chars=MAX_CAMPAIGN_BUDGET_ASSIGNMENT_DISPLAY_DATA_CHARS,
        max_samples_per_outcome=None,
        audit_note=None,
    )


def _bounded_result(
    result: Mapping[str, Any],
    *,
    max_chars: int,
    max_samples_per_outcome: int | None,
    audit_note: str | None,
) -> dict[str, Any]:
    campaigns = result.get("campaigns")
    destination = result.get("destination_budget")
    if not isinstance(campaigns, list):
        raise TypeError("Campaign budget assignment result is missing campaign rows")
    if not isinstance(destination, GoogleAdsCampaignBudgetReference):
        destination = GoogleAdsCampaignBudgetReference.model_validate(destination)
    outcomes = {
        outcome: [row for row in campaigns if row.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }
    normalized = {
        key: [_campaign_sample(row) for row in values] for key, values in outcomes.items()
    }
    return bounded_outcome_result(
        normalized,
        max_chars=max_chars,
        max_samples_per_outcome=max_samples_per_outcome,
        additional_fields={
            "destination_budget": _budget_reference(destination),
            "audit_note": audit_note,
        },
    )


def _campaign_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    campaign = row.get("campaign")
    if not isinstance(campaign, GoogleAdsCampaignReference):
        campaign = GoogleAdsCampaignReference.model_validate(campaign)
    previous_budget = row.get("previous_budget")
    if not isinstance(previous_budget, GoogleAdsCampaignBudgetReference):
        previous_budget = GoogleAdsCampaignBudgetReference.model_validate(previous_budget)
    requested_budget = row.get("requested_budget")
    if not isinstance(requested_budget, GoogleAdsCampaignBudgetReference):
        requested_budget = GoogleAdsCampaignBudgetReference.model_validate(requested_budget)
    return {
        "campaign": campaign.model_dump(mode="json"),
        "previous_budget": _budget_reference(previous_budget),
        "requested_budget": _budget_reference(requested_budget),
        "outcome": row.get("outcome"),
        "external_ref": _optional_text(row.get("external_ref"), 1_000),
        "error_code": _optional_text(row.get("error_code"), 100),
        "message": _optional_text(row.get("message"), 500),
    }


def _budget_reference(reference: GoogleAdsCampaignBudgetReference) -> dict[str, Any]:
    return reference.model_copy(update={"campaign_labels": ()}).model_dump(mode="json")


def _optional_text(value: Any, max_chars: int) -> str | None:
    return str(value)[:max_chars] if value is not None else None
