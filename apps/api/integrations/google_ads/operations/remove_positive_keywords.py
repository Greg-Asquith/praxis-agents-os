# apps/api/integrations/google_ads/operations/remove_positive_keywords.py

"""Removes positive Google Ads keywords with exact outcome accounting."""

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


def positive_keyword_removal_failure_ledger(
    keyword_ids: Sequence[tuple[str, str]],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Accounts for every keyword when a request has no usable response body."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Keyword removal failures must be failed or unverified")
    normalized_ids = _validate_keyword_ids(keyword_ids)
    return _ledger(
        normalized_ids,
        outcomes=[(outcome, None, error_code, message) for _ in normalized_ids],
    )


async def remove_positive_keywords(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    keyword_ids: Sequence[tuple[str, str]],
) -> GoogleAdsMutationLedger:
    """Removes the selected keywords and accounts for every provider result."""
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_ids = _validate_keyword_ids(keyword_ids)

    parent_fields = [
        {"ad_group_id": keyword_id[0], "criterion_id": keyword_id[1]}
        for keyword_id in normalized_ids
    ]
    submitted = list(enumerate(parent_fields))
    resource_names = [
        f"customers/{normalized_customer_id}/adGroupCriteria/{keyword_id[0]}~{keyword_id[1]}"
        for keyword_id in normalized_ids
    ]
    payload = await client.post(
        f"customers/{normalized_customer_id}/adGroupCriteria:mutate",
        operation="remove_positive_keywords",
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
        unattributed_error_fields={"ad_group_id": "", "criterion_id": ""},
        default_message="Keyword removal failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    outcomes = reconcile_exact_mutation_outcomes(
        results,
        expected_resource_names=resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return _ledger(normalized_ids, outcomes=outcomes)


def _validate_keyword_ids(keyword_ids: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if not keyword_ids:
        raise ValueError("Google Ads keyword removals cannot be empty")
    if len(keyword_ids) > 500:
        raise ValueError("Google Ads keyword removals accept at most 500 keywords")
    if any(len(pair) != 2 for pair in keyword_ids):
        raise ValueError("Keyword removals require an ad group and criterion id")
    if any(not value.isascii() or not value.isdigit() for pair in keyword_ids for value in pair):
        raise ValueError("Google Ads keyword ids must contain only digits")
    if len(set(keyword_ids)) != len(keyword_ids):
        raise ValueError("Google Ads keyword removals must be unique")
    return tuple(keyword_ids)


def _ledger(
    keyword_ids: Sequence[tuple[str, str]],
    *,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    parent_fields = [
        {"ad_group_id": keyword_id[0], "criterion_id": keyword_id[1]} for keyword_id in keyword_ids
    ]
    submitted = list(enumerate(parent_fields))
    return build_mutation_ledger(
        family="positive_keyword_removals",
        action="remove",
        parent_fields=parent_fields,
        skipped_indices={},
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="removed",
            skipped_key="skipped",
            errors_key="keyword_errors",
        ),
    )
