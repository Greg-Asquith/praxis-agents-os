# apps/api/integrations/google_ads/operations/delete_labels.py

"""Delete Google Ads labels with exact outcome accounting."""

from collections.abc import Sequence

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_exact_mutation_outcomes,
)
from .utils import grouped_partial_failure_errors

MAX_LABEL_DELETIONS = 50


async def delete_labels(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    label_ids: Sequence[str],
) -> GoogleAdsMutationLedger:
    """Deletes each label; Google Ads removes the label's associations with it."""
    customer = normalize_customer_id(customer_id)
    _validate_label_ids(label_ids)
    parent_fields = [{"label_id": label_id} for label_id in label_ids]
    resource_names = [f"customers/{customer}/labels/{label_id}" for label_id in label_ids]
    payload = await client.post(
        f"customers/{customer}/labels:mutate",
        operation="delete_labels",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [{"remove": name} for name in resource_names],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        parent_fields,
        value_to_error_fields=lambda fields: fields,
        unattributed_error_fields={"label_id": ""},
        default_message="Label deletion failed",
    )
    outcomes = reconcile_exact_mutation_outcomes(
        payload.get("results") if isinstance(payload, dict) else None,
        expected_resource_names=resource_names,
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return build_mutation_ledger(
        family="labels",
        action="delete",
        parent_fields=parent_fields,
        skipped_indices={},
        submitted=list(enumerate(parent_fields)),
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="deleted",
            skipped_key="skipped",
            errors_key="label_errors",
        ),
    )


def _validate_label_ids(label_ids: Sequence[str]) -> None:
    if not label_ids or len(label_ids) > MAX_LABEL_DELETIONS:
        raise ValueError(f"Google Ads label deletions require 1 to {MAX_LABEL_DELETIONS} labels")
    if len(set(label_ids)) != len(label_ids):
        raise ValueError("Google Ads label deletions must be unique")
    if any(not label_id.isascii() or not label_id.isdigit() for label_id in label_ids):
        raise ValueError("Google Ads label ids must contain only digits")
