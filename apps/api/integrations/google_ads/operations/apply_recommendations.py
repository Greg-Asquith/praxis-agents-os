# apps/api/integrations/google_ads/operations/apply_recommendations.py

"""Apply selected Google Ads recommendations with exact outcome accounting."""

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

type GoogleAdsRecommendationApplyOperation = tuple[
    str,
    str,
    tuple[str, Mapping[str, Any]] | None,
]

_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


def recommendation_failure_ledger(
    recommendations: Sequence[GoogleAdsRecommendationApplyOperation],
    *,
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Account for every recommendation when a request has no usable response body."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Recommendation failure outcomes must be failed or unverified")
    parent_fields = [
        {
            "recommendation_resource_name": resource_name,
            "recommendation_type": recommendation_type,
        }
        for resource_name, recommendation_type, _parameters in recommendations
    ]
    submitted = [(index, fields) for index, fields in enumerate(parent_fields)]
    return build_mutation_ledger(
        family="recommendations",
        action="apply",
        parent_fields=parent_fields,
        skipped_indices={},
        submitted=submitted,
        outcomes=[(outcome, None, error_code, message) for _index, _fields in submitted],
        projection=GoogleAdsMutationProjection(
            applied_key="applied",
            skipped_key="skipped",
            errors_key="recommendation_errors",
        ),
    )


async def apply_recommendations(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    recommendations: Sequence[GoogleAdsRecommendationApplyOperation],
) -> GoogleAdsMutationLedger:
    """Applies recommendations once and reconciles every provider operation index."""
    normalized_customer_id = normalize_customer_id(customer_id)
    parent_fields = [
        {
            "recommendation_resource_name": resource_name,
            "recommendation_type": recommendation_type,
        }
        for resource_name, recommendation_type, _parameters in recommendations
    ]
    submitted = [(index, fields) for index, fields in enumerate(parent_fields)]
    operations = []
    expected_resource_names = []
    for resource_name, _recommendation_type, parameters in recommendations:
        if recommendation_customer_id(resource_name) != normalized_customer_id:
            raise ValueError("Google Ads recommendation resource name is outside the account")
        operation: dict[str, Any] = {"resourceName": resource_name}
        if parameters is not None:
            parameter_type, parameter_fields = parameters
            operation[parameter_type] = dict(parameter_fields)
        operations.append(operation)
        expected_resource_names.append(resource_name)

    payload = await client.post(
        f"customers/{normalized_customer_id}/recommendations:apply",
        operation="apply_recommendations",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        parent_fields,
        value_to_error_fields=lambda fields: fields,
        unattributed_error_fields={
            "recommendation_resource_name": "",
            "recommendation_type": "",
        },
        default_message="Recommendation apply failed",
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
            for index, _fields in submitted
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

    return build_mutation_ledger(
        family="recommendations",
        action="apply",
        parent_fields=parent_fields,
        skipped_indices={},
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="applied",
            skipped_key="skipped",
            errors_key="recommendation_errors",
        ),
    )
