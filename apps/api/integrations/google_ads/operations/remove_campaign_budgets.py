# apps/api/integrations/google_ads/operations/remove_campaign_budgets.py

"""Remove unused Google Ads campaign budgets with exact outcome accounting."""

from collections.abc import Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_exact_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors


def campaign_budget_removal_failure_ledger(
    budget_ids: Sequence[str],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Accounts for every budget when a request has no usable response body."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Campaign budget removal failures must be failed or unverified")
    normalized_ids = _validate_budget_ids(budget_ids)
    return _ledger(
        normalized_ids,
        outcomes=[(outcome, None, error_code, message) for _ in normalized_ids],
    )


async def remove_campaign_budgets(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    budget_ids: Sequence[str],
) -> GoogleAdsMutationLedger:
    """Removes the selected campaign budgets and accounts for every provider result."""
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_ids = _validate_budget_ids(budget_ids)

    parent_fields = [{"budget_id": budget_id} for budget_id in normalized_ids]
    submitted = list(enumerate(parent_fields))
    resource_names = [
        f"customers/{normalized_customer_id}/campaignBudgets/{budget_id}"
        for budget_id in normalized_ids
    ]
    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignBudgets:mutate",
        operation="remove_campaign_budgets",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [{"remove": resource_name} for resource_name in resource_names],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={"budget_id": ""},
        default_message="Campaign budget removal failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    outcomes = reconcile_exact_mutation_outcomes(
        results,
        expected_resource_names=resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return _ledger(normalized_ids, outcomes=outcomes)


def _validate_budget_ids(budget_ids: Sequence[str]) -> tuple[str, ...]:
    if not budget_ids:
        raise ValueError("Google Ads campaign budget removals cannot be empty")
    if len(budget_ids) > 50:
        raise ValueError("Google Ads campaign budget removals accept at most 50 budgets")
    if any(not budget_id.isdigit() for budget_id in budget_ids):
        raise ValueError("Google Ads campaign budget ids must contain only digits")
    if len(set(budget_ids)) != len(budget_ids):
        raise ValueError("Google Ads campaign budget removals must be unique")
    return tuple(budget_ids)


def _ledger(
    budget_ids: Sequence[str],
    *,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    parent_fields = [{"budget_id": budget_id} for budget_id in budget_ids]
    submitted = list(enumerate(parent_fields))
    return build_mutation_ledger(
        family="campaign_budget_removals",
        action="remove",
        parent_fields=parent_fields,
        skipped_indices={},
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="removed",
            skipped_key="skipped",
            errors_key="budget_errors",
        ),
    )
