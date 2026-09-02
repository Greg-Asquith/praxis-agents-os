# apps/api/integrations/google_ads/operations/update_campaign_budget_amounts.py

"""Update Google Ads campaign budget amounts with exact outcome accounting."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
    reconcile_exact_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors

type GoogleAdsCampaignBudgetPeriod = Literal["DAILY", "CUSTOM_PERIOD"]


@dataclass(frozen=True, slots=True)
class GoogleAdsCampaignBudgetAmountChange:
    """One live-verified campaign budget amount change."""

    budget_id: str
    period: GoogleAdsCampaignBudgetPeriod
    previous_amount_micros: int
    requested_amount_micros: int


async def update_campaign_budget_amounts(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    changes: Sequence[GoogleAdsCampaignBudgetAmountChange],
) -> GoogleAdsMutationLedger:
    """Update only the amount field selected by each budget's live period."""
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    submitted: list[tuple[int, dict[str, str]]] = []
    operations: list[dict[str, Any]] = []
    expected_resource_names: list[str] = []

    if not changes:
        raise ValueError("Google Ads campaign budget updates cannot be empty")
    if len(changes) > 100:
        raise ValueError("Google Ads campaign budget updates accept at most 100 changes")
    for change in changes:
        _validate_change(change)
        identity = {"budget_id": change.budget_id}
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        resource_name = f"customers/{normalized_customer_id}/campaignBudgets/{change.budget_id}"
        if change.previous_amount_micros == change.requested_amount_micros:
            skipped_indices[parent_index] = "already set"
            skipped_refs.append((freeze_fields(identity), resource_name))
            continue

        amount_field = "amountMicros" if change.period == "DAILY" else "totalAmountMicros"
        submitted.append((parent_index, identity))
        expected_resource_names.append(resource_name)
        operations.append(
            {
                "update": {
                    "resourceName": resource_name,
                    amount_field: str(change.requested_amount_micros),
                },
                "updateMask": amount_field,
            }
        )

    if len({change.budget_id for change in changes}) != len(changes):
        raise ValueError("Google Ads campaign budget updates must be unique")
    if not operations:
        return _ledger(
            parent_fields,
            skipped_indices=skipped_indices,
            skipped_refs=skipped_refs,
            submitted=(),
            outcomes=(),
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignBudgets:mutate",
        operation="update_campaign_budget_amounts",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={"budget_id": ""},
        default_message="Campaign budget amount update failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    outcomes = reconcile_exact_mutation_outcomes(
        results,
        expected_resource_names=expected_resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=skipped_refs,
        submitted=submitted,
        outcomes=outcomes,
    )


def _validate_change(change: GoogleAdsCampaignBudgetAmountChange) -> None:
    if not change.budget_id.isdigit():
        raise ValueError("Google Ads campaign budget ids must contain only digits")
    if change.period not in {"DAILY", "CUSTOM_PERIOD"}:
        raise ValueError("Google Ads campaign budget period is unsupported")
    if change.previous_amount_micros < 0 or change.requested_amount_micros <= 0:
        raise ValueError("Google Ads campaign budget amounts are invalid")


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    skipped_refs: Sequence[tuple[tuple[tuple[str, str], ...], str]],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    ledger = build_mutation_ledger(
        family="campaign_budget_amounts",
        action="update",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="updated",
            skipped_key="already_set",
            errors_key="budget_errors",
        ),
    )
    return replace(ledger, skipped_external_refs=tuple(skipped_refs))
