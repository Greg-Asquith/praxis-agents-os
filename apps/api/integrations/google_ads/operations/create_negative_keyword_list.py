# apps/api/integrations/google_ads/operations/create_negative_keyword_list.py

"""Create Google Ads negative keyword shared sets with duplicate skipping."""

import re
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .mutation_outcomes import (
    GoogleAdsMutationLedger,
    GoogleAdsMutationProjection,
    build_mutation_ledger,
    freeze_fields,
)
from .utils import grouped_partial_failure_errors, stream_rows

_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"
_SHARED_SET_RESOURCE_PATTERN = re.compile(r"customers/\d+/sharedSets/\d+")


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
                "SELECT shared_set.id, shared_set.name FROM shared_set "
                "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' "
                "AND shared_set.status != 'REMOVED'"
            )
        },
    )
    existing_by_name = {
        str(shared_set.get("name", "")).casefold(): str(shared_set.get("id", ""))
        for row in stream_rows(existing_payload)
        if isinstance((shared_set := row.get("sharedSet")), dict)
        and str(shared_set.get("name", ""))
        and str(shared_set.get("id", "")).isdigit()
    }
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
        return _with_existing_refs(
            _ledger(names, skipped_indices=skipped_indices, submitted=(), outcomes=()),
            names,
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
    results = payload.get("results") if isinstance(payload, dict) else None
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return _with_existing_refs(
            _ledger(
                names,
                skipped_indices=skipped_indices,
                submitted=submitted,
                outcomes=[
                    ("unverified", None, diagnostic["error_code"], diagnostic["message"])
                    for _ in create_names
                ],
            ),
            names,
            existing_by_name,
        )
    if not _valid_results(
        results,
        expected_customer_id=normalized_customer_id,
        operation_count=len(create_names),
        indexed_errors=indexed_errors,
    ):
        return _with_existing_refs(
            _ledger(
                names,
                skipped_indices=skipped_indices,
                submitted=submitted,
                outcomes=[
                    (
                        "failed" if index in indexed_errors else "unverified",
                        None,
                        (
                            indexed_errors[index]["error_code"]
                            if index in indexed_errors
                            else _UNACCOUNTED_RESPONSE_CODE
                        ),
                        (
                            indexed_errors[index]["message"]
                            if index in indexed_errors
                            else _UNACCOUNTED_RESPONSE_MESSAGE
                        ),
                    )
                    for index in range(len(create_names))
                ],
            ),
            names,
            existing_by_name,
        )

    outcomes = []
    for index, (_name, item) in enumerate(zip(create_names, results, strict=True)):
        if (error := indexed_errors.get(index)) is not None:
            outcomes.append(("failed", None, error["error_code"], error["message"]))
        else:
            outcomes.append(("applied", item["resourceName"], None, None))
    return _with_existing_refs(
        _ledger(names, skipped_indices=skipped_indices, submitted=submitted, outcomes=outcomes),
        names,
        existing_by_name,
    )


def _with_existing_refs(
    ledger: GoogleAdsMutationLedger,
    names: list[str],
    existing_by_name: Mapping[str, str],
) -> GoogleAdsMutationLedger:
    return replace(
        ledger,
        skipped_external_refs=tuple(
            (freeze_fields({"name": name}), f"sharedSets/{existing_by_name[name.casefold()]}")
            for name in names
            if name.casefold() in existing_by_name
        ),
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


def _valid_results(
    results: Any,
    *,
    expected_customer_id: str,
    operation_count: int,
    indexed_errors: Mapping[int, dict[str, str]],
) -> bool:
    if not isinstance(results, list) or len(results) != operation_count:
        return False
    seen: set[str] = set()
    for index, item in enumerate(results):
        if not isinstance(item, Mapping):
            return False
        resource_name = item.get("resourceName")
        if index in indexed_errors:
            if resource_name is not None:
                return False
            continue
        if (
            not isinstance(resource_name, str)
            or _SHARED_SET_RESOURCE_PATTERN.fullmatch(resource_name) is None
            or not resource_name.startswith(f"customers/{expected_customer_id}/sharedSets/")
            or resource_name in seen
        ):
            return False
        seen.add(resource_name)
    return True
