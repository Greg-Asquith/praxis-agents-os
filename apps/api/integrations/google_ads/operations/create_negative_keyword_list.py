# apps/api/integrations/google_ads/operations/create_negative_keyword_list.py

"""Create Google Ads negative keyword shared sets with duplicate skipping."""

import re
from collections.abc import Mapping
from typing import Any

from ..client import GoogleAdsClient, normalize_customer_id
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
) -> dict[str, Any]:
    normalized_customer_id = normalize_customer_id(customer_id)
    existing_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_negative_keyword_lists",
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT shared_set.id, shared_set.name FROM shared_set "
                "WHERE shared_set.type = 'NEGATIVE_KEYWORDS' "
                "AND shared_set.status != 'REMOVED'"
            )
        },
    )
    existing_names = {
        str(shared_set.get("name", "")).casefold()
        for row in stream_rows(existing_payload)
        if isinstance((shared_set := row.get("sharedSet")), dict)
        and str(shared_set.get("name", ""))
    }
    skipped_existing = [name for name in names if name.casefold() in existing_names]
    create_names = [name for name in names if name.casefold() not in existing_names]
    if not create_names:
        return {
            "created_names": [],
            "resource_names": [],
            "skipped_existing": skipped_existing,
            "list_errors": [],
        }

    payload = await client.post(
        f"customers/{normalized_customer_id}/sharedSets:mutate",
        operation="create_negative_keyword_list",
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
        return _failed_result(
            create_names,
            skipped_existing=skipped_existing,
            indexed_errors=dict.fromkeys(range(len(create_names)), diagnostic),
        )
    if not _valid_results(
        results,
        expected_customer_id=normalized_customer_id,
        operation_count=len(create_names),
        indexed_errors=indexed_errors,
    ):
        return _failed_result(
            create_names,
            skipped_existing=skipped_existing,
            indexed_errors=indexed_errors,
        )

    created_names: list[str] = []
    resource_names: list[str] = []
    list_errors: list[dict[str, str]] = []
    for index, (name, item) in enumerate(zip(create_names, results, strict=True)):
        if (error := indexed_errors.get(index)) is not None:
            list_errors.append(error)
            continue
        created_names.append(name)
        resource_names.append(item["resourceName"])
    return {
        "created_names": created_names,
        "resource_names": resource_names,
        "skipped_existing": skipped_existing,
        "list_errors": list_errors,
    }


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


def _failed_result(
    names: list[str],
    *,
    skipped_existing: list[str],
    indexed_errors: Mapping[int, dict[str, str]],
) -> dict[str, Any]:
    return {
        "created_names": [],
        "resource_names": [],
        "skipped_existing": skipped_existing,
        "list_errors": [
            _list_error(name, indexed_errors.get(index)) for index, name in enumerate(names)
        ],
    }


def _list_error(name: str, diagnostic: dict[str, str] | None) -> dict[str, str]:
    return {
        "name": name,
        "message": diagnostic["message"] if diagnostic else _UNACCOUNTED_RESPONSE_MESSAGE,
        "error_code": (diagnostic["error_code"] if diagnostic else _UNACCOUNTED_RESPONSE_CODE),
    }
