# apps/api/integrations/google_ads/operations/dismiss_recommendations.py

"""Dismiss selected Google Ads recommendations with exact outcome accounting."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from ..recommendation_utils import recommendation_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from .utils import grouped_partial_failure_errors, valid_exact_mutation_results

type GoogleAdsRecommendationDismissOperation = tuple[str, str, bool]

_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


def recommendation_dismiss_failure_ledger(
    recommendations: Sequence[GoogleAdsRecommendationDismissOperation],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Accounts for every recommendation when a request has no usable response body."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Recommendation failure outcomes must be failed or unverified")
    parent_fields, skipped_indices, submitted, _operations, _expected = _prepare(
        recommendations,
        customer_id=None,
    )
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=[(outcome, None, error_code, message) for _ in submitted],
    )


async def dismiss_recommendations(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    recommendations: Sequence[GoogleAdsRecommendationDismissOperation],
) -> GoogleAdsMutationLedger:
    """Dismisses recommendations once and reconciles every provider operation index."""
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields, skipped_indices, submitted, operations, expected_resource_names = _prepare(
        recommendations,
        customer_id=normalized_customer_id,
    )
    if not operations:
        return _ledger(
            parent_fields,
            skipped_indices=skipped_indices,
            submitted=(),
            outcomes=(),
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/recommendations:dismiss",
        operation="dismiss_recommendations",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        submitted,
        value_to_error_fields=lambda item: item[1],
        unattributed_error_fields={
            "recommendation_resource_name": "",
            "recommendation_type": "",
        },
        default_message="Recommendation dismissal failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        outcomes = [
            (
                (
                    "failed",
                    None,
                    indexed_errors[index]["error_code"],
                    indexed_errors[index]["message"],
                )
                if index in indexed_errors
                else (
                    "unverified",
                    None,
                    diagnostic["error_code"],
                    diagnostic["message"],
                )
            )
            for index in range(len(submitted))
        ]
    elif not valid_exact_mutation_results(
        results,
        expected_resource_names=expected_resource_names,
        indexed_errors=indexed_errors,
    ):
        outcomes = [
            (
                "failed" if index in indexed_errors else "unverified",
                None,
                indexed_errors.get(index, {}).get("error_code", _UNACCOUNTED_RESPONSE_CODE),
                indexed_errors.get(index, {}).get("message", _UNACCOUNTED_RESPONSE_MESSAGE),
            )
            for index in range(len(submitted))
        ]
    else:
        outcomes = [
            (
                (
                    "failed",
                    None,
                    indexed_errors[index]["error_code"],
                    indexed_errors[index]["message"],
                )
                if index in indexed_errors
                else ("applied", item["resourceName"], None, None)
            )
            for index, item in enumerate(results)
        ]
    return _ledger(
        parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
    )


def _prepare(
    recommendations: Sequence[GoogleAdsRecommendationDismissOperation],
    *,
    customer_id: str | None,
) -> tuple[
    list[dict[str, str]],
    dict[int, str],
    list[tuple[int, dict[str, str]]],
    list[dict[str, str]],
    list[str],
]:
    parent_fields: list[dict[str, str]] = []
    skipped_indices: dict[int, str] = {}
    submitted: list[tuple[int, dict[str, str]]] = []
    operations: list[dict[str, str]] = []
    expected_resource_names: list[str] = []
    for resource_name, recommendation_type, already_dismissed in recommendations:
        if customer_id is not None and recommendation_customer_id(resource_name) != customer_id:
            raise ValueError("Google Ads recommendation resource name is outside the account")
        identity = {
            "recommendation_resource_name": resource_name,
            "recommendation_type": recommendation_type,
        }
        parent_index = len(parent_fields)
        parent_fields.append(identity)
        if already_dismissed:
            skipped_indices[parent_index] = "already dismissed"
            continue
        submitted.append((parent_index, identity))
        operations.append({"resourceName": resource_name})
        expected_resource_names.append(resource_name)
    return parent_fields, skipped_indices, submitted, operations, expected_resource_names


def _ledger(
    parent_fields: Sequence[Mapping[str, object]],
    *,
    skipped_indices: Mapping[int, str],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    return build_mutation_ledger(
        family="recommendations",
        action="dismiss",
        parent_fields=parent_fields,
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="dismissed",
            skipped_key="already_dismissed",
            errors_key="recommendation_errors",
        ),
    )
