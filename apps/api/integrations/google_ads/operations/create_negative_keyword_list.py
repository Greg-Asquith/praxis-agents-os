# apps/api/integrations/google_ads/operations/create_negative_keyword_list.py

"""Create Google Ads negative keyword shared sets with duplicate skipping."""

import re
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    reconcile_created_mutation_outcomes,
    with_existing_name_refs,
)
from .utils import grouped_partial_failure_errors, resource_names_by_casefold_name, stream_rows


async def create_negative_keyword_list(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    names: list[str],
) -> GoogleAdsMutationLedger:
    normalized_customer_id = normalize_customer_id(customer_id)
    existing_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_negative_keyword_lists",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT shared_set.resource_name, shared_set.name FROM shared_set "
                "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' "
                "AND shared_set.status != 'REMOVED'"
            )
        },
    )
    existing_by_name = resource_names_by_casefold_name(
        stream_rows(existing_payload),
        row_key="sharedSet",
        owned_prefix=f"customers/{normalized_customer_id}/sharedSets/",
    )
    skipped_indices = {
        index: "already_exists"
        for index, name in enumerate(names)
        if name.casefold() in existing_by_name
    }
    submitted = [
        (index, {"name": name}) for index, name in enumerate(names) if index not in skipped_indices
    ]
    create_names = [fields["name"] for _, fields in submitted]
    if not create_names:
        return with_existing_name_refs(
            _ledger(names, skipped_indices=skipped_indices, submitted=(), outcomes=()),
            existing_by_name,
        )

    payload = await client.post(
        f"customers/{normalized_customer_id}/sharedSets:mutate",
        operation="create_negative_keyword_list",
        policy=IntegrationRequestPolicy.MUTATION,
        login_customer_id=login_customer_id,
        json={
            "operations": [
                {"create": {"name": name, "type": "NEGATIVE_KEYWORDS"}} for name in create_names
            ],
            "partialFailure": True,
        },
    )
    indexed_errors, unattributed_errors = grouped_partial_failure_errors(
        payload,
        create_names,
        value_to_error_fields=lambda name: {"name": name},
        unattributed_error_fields={"name": ""},
        default_message="Negative keyword list creation failed",
    )
    outcomes = reconcile_created_mutation_outcomes(
        payload.get("results") if isinstance(payload, dict) else None,
        resource_pattern=re.compile(rf"customers/{normalized_customer_id}/sharedSets/\d+"),
        operation_count=len(create_names),
        indexed_errors=indexed_errors,
        unattributed_errors=unattributed_errors,
    )
    return with_existing_name_refs(
        _ledger(names, skipped_indices=skipped_indices, submitted=submitted, outcomes=outcomes),
        existing_by_name,
    )


def _ledger(
    names: list[str],
    *,
    skipped_indices: dict[int, str],
    submitted: Any,
    outcomes: Any,
) -> GoogleAdsMutationLedger:
    return build_mutation_ledger(
        family="negative_keyword_lists",
        action="create",
        parent_fields=[{"name": name} for name in names],
        skipped_indices=skipped_indices,
        submitted=submitted,
        outcomes=outcomes,
        projection=GoogleAdsMutationProjection(
            applied_key="created",
            skipped_key="skipped_existing",
            errors_key="list_errors",
        ),
    )
