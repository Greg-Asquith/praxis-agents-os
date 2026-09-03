# apps/api/integrations/google_ads/operations/update_positive_keyword_status.py

"""Update Google Ads positive-keyword status with exact outcome accounting."""

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

type GoogleAdsPositiveKeywordStatus = Literal["ENABLED", "PAUSED"]


@dataclass(frozen=True, slots=True)
class GoogleAdsPositiveKeywordStatusChange:
    """One live-verified positive-keyword status change."""

    ad_group_id: str
    criterion_id: str
    previous_status: GoogleAdsPositiveKeywordStatus
    requested_status: GoogleAdsPositiveKeywordStatus


def positive_keyword_status_failure_ledger(
    changes: Sequence[GoogleAdsPositiveKeywordStatusChange],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Account for every status change when no usable response body exists."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Positive keyword status failures must be failed or unverified")
    parent_fields, skipped_indices, submitted = _partition_changes(changes)
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        skipped_refs=(),
        submitted=submitted,
        outcomes=[(outcome, None, error_code, message) for _ in submitted],
    )


async def update_positive_keyword_status(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    changes: Sequence[GoogleAdsPositiveKeywordStatusChange],
) -> GoogleAdsMutationLedger:
    """Update only status for up to 500 live positive keyword criteria."""
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields, skipped_indices, submitted = _partition_changes(changes)
    skipped_refs: list[tuple[tuple[tuple[str, str], ...], str]] = []
    operations: list[dict[str, Any]] = []
    expected_resource_names: list[str] = []
    for parent_index, identity in enumerate(parent_fields):
        change = changes[parent_index]
        resource_name = (
            f"customers/{normalized_customer_id}/adGroupCriteria/"
            f"{change.ad_group_id}~{change.criterion_id}"
        )
        if parent_index in skipped_indices:
            skipped_refs.append((freeze_fields(identity), resource_name))
            continue
        expected_resource_names.append(resource_name)
        operations.append(
            {
                "update": {
                    "resourceName": resource_name,
                    "status": change.requested_status,
                },
                "updateMask": "status",
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
        f"customers/{normalized_customer_id}/adGroupCriteria:mutate",
        operation="update_positive_keyword_status",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={"ad_group_id": "", "criterion_id": ""},
        default_message="Positive keyword status update failed",
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


def _partition_changes(
    changes: Sequence[GoogleAdsPositiveKeywordStatusChange],
) -> tuple[list[dict[str, str]], dict[int, str], list[tuple[int, dict[str, str]]]]:
    if not changes:
        raise ValueError("Google Ads positive keyword status updates cannot be empty")
    if len(changes) > 500:
        raise ValueError("Google Ads positive keyword status updates accept at most 500 changes")
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    submitted: list[tuple[int, dict[str, str]]] = []
    identities: set[tuple[str, str]] = set()
    for change in changes:
        _validate_change(change)
        identity_key = (change.ad_group_id, change.criterion_id)
        if identity_key in identities:
            raise ValueError("Google Ads positive keyword status updates must be unique")
        identities.add(identity_key)
        identity = {"ad_group_id": change.ad_group_id, "criterion_id": change.criterion_id}
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        if change.previous_status == change.requested_status:
            skipped_indices[parent_index] = "already set"
        else:
            submitted.append((parent_index, identity))
    return parent_fields, skipped_indices, submitted


def _validate_change(change: GoogleAdsPositiveKeywordStatusChange) -> None:
    if not change.ad_group_id.isdigit() or not change.criterion_id.isdigit():
        raise ValueError("Google Ads positive keyword ids must contain only digits")
    if change.previous_status not in {"ENABLED", "PAUSED"} or change.requested_status not in {
        "ENABLED",
        "PAUSED",
    }:
        raise ValueError("Google Ads positive keyword status is invalid")


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    skipped_refs: Sequence[tuple[tuple[tuple[str, str], ...], str]],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    ledger = build_mutation_ledger(
        family="positive_keyword_status",
        action="update_status",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="updated",
            skipped_key="already_set",
            errors_key="keyword_errors",
        ),
    )
    return replace(ledger, skipped_external_refs=tuple(skipped_refs))
