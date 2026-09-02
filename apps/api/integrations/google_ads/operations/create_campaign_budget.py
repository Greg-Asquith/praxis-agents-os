# apps/api/integrations/google_ads/operations/create_campaign_budget.py

"""Create one Google Ads campaign budget with exact mutation accounting."""

import re
from collections.abc import Mapping
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
)
from .utils import grouped_partial_failure_errors

_RESOURCE_PATTERN = re.compile(r"customers/(\d+)/campaignBudgets/(\d+)")
_UNACCOUNTED_CODE = "UNACCOUNTED_OPERATION"
_UNACCOUNTED_MESSAGE = "Google Ads did not account for the campaign budget creation"


async def create_campaign_budget(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    name: str,
    period: Literal["DAILY", "CUSTOM_PERIOD"],
    amount_micros: int,
    explicitly_shared: bool,
    delivery_method: Literal["STANDARD", "ACCELERATED"],
) -> GoogleAdsMutationLedger:
    normalized_customer_id = normalize_customer_id(customer_id)
    amount_field = "amountMicros" if period == "DAILY" else "totalAmountMicros"
    identity = {
        "name": name,
        "period": period,
        "amount_micros": str(amount_micros),
        "delivery_method": delivery_method,
        "explicitly_shared": str(explicitly_shared).lower(),
    }
    payload = await client.post(
        f"customers/{normalized_customer_id}/campaignBudgets:mutate",
        operation="create_campaign_budget",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [
                {
                    "create": {
                        "name": name,
                        "period": period,
                        amount_field: str(amount_micros),
                        "explicitlyShared": explicitly_shared,
                        "deliveryMethod": delivery_method,
                    }
                }
            ],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        [name],
        value_to_error_fields=lambda _name: identity,
        unattributed_error_fields=identity,
        default_message="Campaign budget creation failed",
    )
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        outcome = ("unverified", None, diagnostic["error_code"], diagnostic["message"])
    elif not _valid_results(
        results, customer_id=normalized_customer_id, has_indexed_error=0 in indexed_errors
    ):
        error = indexed_errors.get(0)
        outcome = (
            "failed" if error else "unverified",
            None,
            error["error_code"] if error else _UNACCOUNTED_CODE,
            error["message"] if error else _UNACCOUNTED_MESSAGE,
        )
    elif (error := indexed_errors.get(0)) is not None:
        outcome = ("failed", None, error["error_code"], error["message"])
    else:
        outcome = ("applied", results[0]["resourceName"], None, None)
    return build_mutation_ledger(
        family="campaign_budgets",
        action="create",
        parent_fields=[identity],
        skipped_indices={},
        submitted=[(0, identity)],
        outcomes=[outcome],
        projection=GoogleAdsMutationProjection(
            applied_key="created",
            skipped_key="skipped",
            errors_key="budget_errors",
        ),
    )


def _valid_results(results: Any, *, customer_id: str, has_indexed_error: bool) -> bool:
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], Mapping):
        return False
    resource_name = results[0].get("resourceName")
    if has_indexed_error:
        return resource_name is None
    if not isinstance(resource_name, str):
        return False
    match = _RESOURCE_PATTERN.fullmatch(resource_name)
    return match is not None and match.group(1) == customer_id
