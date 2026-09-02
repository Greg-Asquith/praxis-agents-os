# apps/api/integrations/google_ads/operations/assign_campaign_budgets.py

"""Assign one existing campaign budget to named Google Ads campaigns."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

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


@dataclass(frozen=True, slots=True)
class GoogleAdsCampaignBudgetAssignment:
    """Describes one live-verified campaign budget replacement."""

    campaign_id: str
    previous_budget_id: str
    requested_budget_id: str


def campaign_budget_assignment_failure_ledger(
    assignments: Sequence[GoogleAdsCampaignBudgetAssignment],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Account for every assignment when a request has no usable response body."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Campaign budget assignment failures must be failed or unverified")
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    submitted: list[tuple[int, dict[str, str]]] = []
    for assignment in assignments:
        identity = {"campaign_id": assignment.campaign_id}
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        if assignment.previous_budget_id == assignment.requested_budget_id:
            skipped_indices[parent_index] = "already set"
            continue
        submitted.append((parent_index, identity))
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=skipped_refs,
        submitted=submitted,
        outcomes=[(outcome, None, error_code, message) for _ in submitted],
    )


async def assign_campaign_budgets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    assignments: Sequence[GoogleAdsCampaignBudgetAssignment],
) -> GoogleAdsMutationLedger:
    """Updates only the campaign budget field for each selected campaign."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if not assignments:
        raise ValueError("Google Ads campaign budget assignments cannot be empty")
    if len(assignments) > 50:
        raise ValueError("Google Ads campaign budget assignments accept at most 50 campaigns")
    if any(
        not value.isdigit()
        for assignment in assignments
        for value in (
            assignment.campaign_id,
            assignment.previous_budget_id,
            assignment.requested_budget_id,
        )
    ):
        raise ValueError("Google Ads campaign and campaign budget ids must contain only digits")
    if len({assignment.campaign_id for assignment in assignments}) != len(assignments):
        raise ValueError("Google Ads campaign budget assignments must use unique campaigns")
    if len({assignment.requested_budget_id for assignment in assignments}) != 1:
        raise ValueError("Google Ads campaign budget assignments require one destination budget")

    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    submitted: list[tuple[int, dict[str, str]]] = []
    operations: list[dict[str, Any]] = []
    expected_resource_names: list[str] = []
    for assignment in assignments:
        identity = {"campaign_id": assignment.campaign_id}
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        campaign_resource = f"customers/{normalized_customer_id}/campaigns/{assignment.campaign_id}"
        if assignment.previous_budget_id == assignment.requested_budget_id:
            skipped_indices[parent_index] = "already set"
            skipped_refs.append((freeze_fields(identity), campaign_resource))
            continue
        destination_resource = (
            f"customers/{normalized_customer_id}/campaignBudgets/{assignment.requested_budget_id}"
        )
        submitted.append((parent_index, identity))
        expected_resource_names.append(campaign_resource)
        operations.append(
            {
                "update": {
                    "resourceName": campaign_resource,
                    "campaignBudget": destination_resource,
                },
                "updateMask": "campaignBudget",
            }
        )

    if not operations:
        return _ledger(
            parent_fields,
            skipped_indices=skipped_indices,
            skipped_refs=skipped_refs,
            submitted=(),
            outcomes=(),
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/campaigns:mutate",
        operation="assign_campaign_budgets",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={"campaign_id": ""},
        default_message="Campaign budget assignment failed",
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


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    skipped_refs: Sequence[tuple[tuple[tuple[str, str], ...], str]],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    ledger = build_mutation_ledger(
        family="campaign_budget_assignments",
        action="assign",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="assigned",
            skipped_key="already_set",
            errors_key="campaign_errors",
        ),
    )
    return replace(ledger, skipped_external_refs=tuple(skipped_refs))
