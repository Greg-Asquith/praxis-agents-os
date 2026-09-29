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
    reconcile_created_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors


def campaign_budget_creation_failure_ledger(
    *,
    name: str,
    period: Literal["DAILY", "CUSTOM_PERIOD"],
    amount_micros: int,
    explicitly_shared: bool,
    delivery_method: Literal["STANDARD", "ACCELERATED"],
    outcome: str,
    error_code: str,
    message: str,
) -> GoogleAdsMutationLedger:
    """Account for a create request that has no usable response body."""
    if outcome not in {"failed", "unverified"}:
        raise ValueError("Campaign budget creation failures must be failed or unverified")
    identity = _identity(
        name=name,
        period=period,
        amount_micros=amount_micros,
        explicitly_shared=explicitly_shared,
        delivery_method=delivery_method,
    )
    return _ledger(identity, outcome=(outcome, None, error_code, message))


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
    identity = _identity(
        name=name,
        period=period,
        amount_micros=amount_micros,
        explicitly_shared=explicitly_shared,
        delivery_method=delivery_method,
    )
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
    [outcome] = reconcile_created_mutation_outcomes(
        payload.get("results") if isinstance(payload, dict) else None,
        resource_pattern=re.compile(rf"customers/{normalized_customer_id}/campaignBudgets/\d+"),
        operation_count=1,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return _ledger(identity, outcome=outcome)


def _identity(
    *,
    name: str,
    period: Literal["DAILY", "CUSTOM_PERIOD"],
    amount_micros: int,
    explicitly_shared: bool,
    delivery_method: Literal["STANDARD", "ACCELERATED"],
) -> dict[str, str]:
    return {
        "name": name,
        "period": period,
        "amount_micros": str(amount_micros),
        "delivery_method": delivery_method,
        "explicitly_shared": str(explicitly_shared).lower(),
    }


def _ledger(identity: Mapping[str, object], *, outcome: Any) -> GoogleAdsMutationLedger:
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
