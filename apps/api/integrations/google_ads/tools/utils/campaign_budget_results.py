# apps/api/integrations/google_ads/tools/utils/campaign_budget_results.py

"""Bounded campaign-budget amount update results."""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from integrations.google_ads.references import GoogleAdsCampaignBudgetReference

from .bounded_outcome_results import bounded_outcome_result

type CampaignBudgetOutcome = Literal["updated", "already_set", "failed", "unverified"]

MAX_CAMPAIGN_BUDGET_AMOUNT_RESULT_CHARS = 12_000
MAX_CAMPAIGN_BUDGET_AMOUNT_DISPLAY_DATA_CHARS = 250_000
MAX_CAMPAIGN_BUDGET_AMOUNT_PUBLIC_RESULT_CHARS = 1_000_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_MODEL_LABELS_PER_SAMPLE = 3
_MODEL_LABEL_CHARS = 80
_DISPLAY_LABELS_PER_SAMPLE = 20
_DISPLAY_LABEL_CHARS = 200
_AUDIT_NOTE = "Complete bounded change evidence is retained in the audit trail."
_OUTCOMES: tuple[CampaignBudgetOutcome, ...] = (
    "updated",
    "already_set",
    "failed",
    "unverified",
)


def bounded_campaign_budget_amount_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return exact counts and representative budget rows for model context."""
    return _bounded_result(
        result,
        max_chars=MAX_CAMPAIGN_BUDGET_AMOUNT_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        max_labels=_MODEL_LABELS_PER_SAMPLE,
        max_label_chars=_MODEL_LABEL_CHARS,
        audit_note=_AUDIT_NOTE,
    )


def display_campaign_budget_amount_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return as many richer budget rows as fit the application display budget."""
    return _bounded_result(
        result,
        max_chars=MAX_CAMPAIGN_BUDGET_AMOUNT_DISPLAY_DATA_CHARS,
        max_samples_per_outcome=None,
        max_labels=_DISPLAY_LABELS_PER_SAMPLE,
        max_label_chars=_DISPLAY_LABEL_CHARS,
        audit_note=None,
    )


def campaign_label_audit_evidence(
    labels: Sequence[str],
    *,
    max_labels: int = 5,
    max_label_chars: int = 100,
) -> dict[str, Any]:
    """Return a bounded label sample with explicit omission evidence."""
    sample = [str(label)[:max_label_chars] for label in labels[:max_labels]]
    return {
        "campaign_label_count": len(labels),
        "campaign_label_sample": sample,
        "campaign_labels_truncated": len(sample) < len(labels)
        or any(len(str(label)) > max_label_chars for label in labels[:max_labels]),
    }


def _bounded_result(
    result: Mapping[str, Any],
    *,
    max_chars: int,
    max_samples_per_outcome: int | None,
    max_labels: int,
    max_label_chars: int,
    audit_note: str | None,
) -> dict[str, Any]:
    budgets = result.get("budgets")
    if not isinstance(budgets, list):
        raise TypeError("Campaign budget amount result is missing budget rows")
    outcomes = {
        outcome: [row for row in budgets if row.get("outcome") == outcome] for outcome in _OUTCOMES
    }
    normalized = {
        key: [
            _budget_sample(
                row,
                max_labels=max_labels,
                max_label_chars=max_label_chars,
            )
            for row in values
        ]
        for key, values in outcomes.items()
    }
    campaign_labels_truncated = any(
        row["campaign_labels_truncated"] for values in normalized.values() for row in values
    )
    return bounded_outcome_result(
        normalized,
        max_chars=max_chars,
        max_samples_per_outcome=max_samples_per_outcome,
        additional_fields={
            "campaign_labels_truncated": campaign_labels_truncated,
            "audit_note": audit_note,
        },
    )


def _budget_sample(
    row: Mapping[str, Any],
    *,
    max_labels: int,
    max_label_chars: int,
) -> dict[str, Any]:
    reference = row.get("reference")
    if not isinstance(reference, GoogleAdsCampaignBudgetReference):
        reference = GoogleAdsCampaignBudgetReference.model_validate(reference)
    label_evidence = campaign_label_audit_evidence(
        reference.campaign_labels,
        max_labels=max_labels,
        max_label_chars=max_label_chars,
    )
    bounded_reference = reference.model_copy(
        update={"campaign_labels": tuple(label_evidence["campaign_label_sample"])}
    )
    return {
        "reference": bounded_reference.model_dump(mode="json"),
        "previous_amount": str(row.get("previous_amount", ""))[:32],
        "requested_amount": str(row.get("requested_amount", ""))[:32],
        "previous_amount_micros": int(row.get("previous_amount_micros", 0)),
        "requested_amount_micros": int(row.get("requested_amount_micros", 0)),
        "outcome": row.get("outcome"),
        "campaign_label_count": label_evidence["campaign_label_count"],
        "campaign_labels_truncated": label_evidence["campaign_labels_truncated"],
        "external_ref": _optional_text(row.get("external_ref"), 1_000),
        "error_code": _optional_text(row.get("error_code"), 100),
        "message": _optional_text(row.get("message"), 500),
    }


def _optional_text(value: Any, max_chars: int) -> str | None:
    return str(value)[:max_chars] if value is not None else None
