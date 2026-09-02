# apps/api/integrations/google_ads/operations/update_campaign_status.py

"""Update only campaign status and surface partial failures per campaign."""

from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_exact_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors


async def update_campaign_status(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
    status: Literal["ENABLED", "PAUSED"],
) -> GoogleAdsMutationLedger:
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_campaign_ids = [normalize_customer_id(value) for value in campaign_ids]
    expected_resource_names = [
        f"customers/{normalized_customer_id}/campaigns/{campaign_id}"
        for campaign_id in normalized_campaign_ids
    ]
    operations = [
        {
            "update": {
                "resourceName": (f"customers/{normalized_customer_id}/campaigns/{campaign_id}"),
                "status": status,
            },
            "updateMask": "status",
        }
        for campaign_id in normalized_campaign_ids
    ]
    payload = await client.post(
        f"customers/{normalized_customer_id}/campaigns:mutate",
        operation="update_campaign_status",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={"operations": operations, "partialFailure": True},
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        normalized_campaign_ids,
        value_to_error_fields=lambda campaign_id: {"campaign_id": campaign_id},
        unattributed_error_fields={"campaign_id": ""},
        default_message="Campaign update failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    submitted = [
        (index, {"campaign_id": campaign_id})
        for index, campaign_id in enumerate(normalized_campaign_ids)
    ]
    outcomes = reconcile_exact_mutation_outcomes(
        results,
        expected_resource_names=expected_resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return _ledger(normalized_campaign_ids, submitted=submitted, outcomes=outcomes)


def _ledger(
    campaign_ids: list[str],
    *,
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    return build_mutation_ledger(
        family="campaign_status",
        action="update",
        parent_fields=[{"campaign_id": campaign_id} for campaign_id in campaign_ids],
        skipped_indices={},
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="updated",
            skipped_key="skipped",
            errors_key="campaign_errors",
        ),
    )
