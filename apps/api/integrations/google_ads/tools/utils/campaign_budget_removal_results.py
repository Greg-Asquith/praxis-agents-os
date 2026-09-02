# apps/api/integrations/google_ads/tools/utils/campaign_budget_removal_results.py

"""Bounded Google Ads campaign budget removal results."""

from collections.abc import Mapping
from typing import Any, Literal

from integrations.google_ads.references import GoogleAdsCampaignBudgetReference

from .bounded_outcome_results import bounded_outcome_result

type CampaignBudgetRemovalOutcome = Literal["removed", "failed", "unverified"]

MAX_CAMPAIGN_BUDGET_REMOVAL_RESULT_CHARS = 12_000
MAX_CAMPAIGN_BUDGET_REMOVAL_DISPLAY_DATA_CHARS = 250_000
MAX_CAMPAIGN_BUDGET_REMOVAL_PUBLIC_RESULT_CHARS = 1_000_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_AUDIT_NOTE = "Complete bounded removal evidence is retained in the audit trail."
_OUTCOMES: tuple[CampaignBudgetRemovalOutcome, ...] = ("removed", "failed", "unverified")


def bounded_campaign_budget_removal_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Returns exact counts and representative removal rows for model context."""
    return _bounded_result(
        result,
        max_chars=MAX_CAMPAIGN_BUDGET_REMOVAL_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        audit_note=_AUDIT_NOTE,
    )


def display_campaign_budget_removal_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Returns every removal row that fits the application display budget."""
    return _bounded_result(
        result,
        max_chars=MAX_CAMPAIGN_BUDGET_REMOVAL_DISPLAY_DATA_CHARS,
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
    budgets = result.get("budgets")
    if not isinstance(budgets, list):
        raise TypeError("Campaign budget removal result is missing budget rows")
    outcomes = {
        outcome: [_budget_sample(row) for row in budgets if row.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }
    return bounded_outcome_result(
        outcomes,
        max_chars=max_chars,
        max_samples_per_outcome=max_samples_per_outcome,
        additional_fields={"audit_note": audit_note},
    )


def _budget_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    reference = row.get("reference")
    if not isinstance(reference, GoogleAdsCampaignBudgetReference):
        reference = GoogleAdsCampaignBudgetReference.model_validate(reference)
    bounded_reference = reference.model_copy(update={"campaign_labels": ()})
    return {
        "reference": bounded_reference.model_dump(mode="json"),
        "previous_status": str(row.get("previous_status", ""))[:64],
        "resulting_status": _optional_text(row.get("resulting_status"), 64),
        "outcome": row.get("outcome"),
        "external_ref": _optional_text(row.get("external_ref"), 1_000),
        "error_code": _optional_text(row.get("error_code"), 100),
        "message": _optional_text(row.get("message"), 500),
    }


def _optional_text(value: Any, max_chars: int) -> str | None:
    return str(value)[:max_chars] if value is not None else None
