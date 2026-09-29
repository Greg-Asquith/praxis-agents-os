# apps/api/integrations/google_ads/operations/create_labels.py

"""Create Google Ads text labels, skipping names the customer already uses."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class GoogleAdsLabelCreate:
    name: str
    description: str | None = None
    background_color: str | None = None


@dataclass(frozen=True, slots=True)
class GoogleAdsLabelCreation:
    """The creation ledger plus the provider rows of labels that already existed."""

    ledger: GoogleAdsMutationLedger
    existing_labels: Mapping[str, Mapping[str, Any]]


async def create_labels(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    labels: Sequence[GoogleAdsLabelCreate],
) -> GoogleAdsLabelCreation:
    """Creates each label whose name is unused and records existing names as skipped.

    Name matching ignores case so a near-duplicate never creates a second label.
    """
    normalized_customer_id = normalize_customer_id(customer_id)
    existing_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_label_names",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": "SELECT label.resource_name, label.id, label.name, label.status, "
            "label.text_label.description, label.text_label.background_color FROM label "
            "WHERE label.status = 'ENABLED'"
        },
    )
    owned_prefix = f"customers/{normalized_customer_id}/labels/"
    existing_rows = stream_rows(existing_payload)
    existing_by_name = resource_names_by_casefold_name(
        existing_rows,
        row_key="label",
        owned_prefix=owned_prefix,
    )
    names = [label.name for label in labels]
    skipped_indices = {
        index: "already_exists"
        for index, name in enumerate(names)
        if name.casefold() in existing_by_name
    }
    submitted = [
        (index, {"name": name}) for index, name in enumerate(names) if index not in skipped_indices
    ]
    outcomes: list[Any] = []
    if submitted:
        creates = [labels[index] for index, _fields in submitted]
        payload = await client.post(
            f"customers/{normalized_customer_id}/labels:mutate",
            operation="create_labels",
            policy=IntegrationRequestPolicy.MUTATION,
            login_customer_id=login_customer_id,
            json={
                "operations": [{"create": _label_payload(label)} for label in creates],
                "partialFailure": True,
            },
        )
        indexed_errors, unattributed_errors = grouped_partial_failure_errors(
            payload,
            [label.name for label in creates],
            value_to_error_fields=lambda name: {"name": name},
            unattributed_error_fields={"name": ""},
            default_message="Label creation failed",
        )
        outcomes = reconcile_created_mutation_outcomes(
            payload.get("results") if isinstance(payload, dict) else None,
            resource_pattern=re.compile(rf"{re.escape(owned_prefix)}\d+"),
            operation_count=len(creates),
            indexed_errors=indexed_errors,
            unattributed_errors=unattributed_errors,
        )
    ledger = with_existing_name_refs(
        build_mutation_ledger(
            family="labels",
            action="create",
            parent_fields=[{"name": name} for name in names],
            skipped_indices=skipped_indices,
            submitted=submitted,
            outcomes=outcomes,
            projection=GoogleAdsMutationProjection(
                applied_key="created",
                skipped_key="skipped_existing",
                errors_key="label_errors",
            ),
        ),
        existing_by_name,
    )
    skipped_refs = {ref for _identity, ref in ledger.skipped_external_refs}
    return GoogleAdsLabelCreation(
        ledger=ledger,
        existing_labels={
            label["resourceName"]: label
            for row in existing_rows
            if isinstance((label := row.get("label")), Mapping)
            and label.get("resourceName") in skipped_refs
        },
    )


def _label_payload(label: GoogleAdsLabelCreate) -> dict[str, Any]:
    text_label = {
        key: value
        for key, value in (
            ("description", label.description),
            ("backgroundColor", label.background_color),
        )
        if value
    }
    return {"name": label.name, **({"textLabel": text_label} if text_label else {})}
