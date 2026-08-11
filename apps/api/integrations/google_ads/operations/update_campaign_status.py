# apps/api/integrations/google_ads/operations/update_campaign_status.py

"""Update only campaign status and surface partial failures per campaign."""

from collections.abc import Mapping
from typing import Any, Literal

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import grouped_partial_failure_errors

_UNACCOUNTED_RESPONSE_MESSAGE = "Google Ads did not account for this submitted operation"
_UNACCOUNTED_RESPONSE_CODE = "UNACCOUNTED_OPERATION"


async def update_campaign_status(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: list[str],
    status: Literal["ENABLED", "PAUSED"],
) -> dict[str, Any]:
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
    if unattributed_errors:
        diagnostic = unattributed_errors[0]
        return _failed_result(
            normalized_campaign_ids,
            indexed_errors=dict.fromkeys(range(len(normalized_campaign_ids)), diagnostic),
        )
    if not _valid_results(
        results,
        expected_resource_names=expected_resource_names,
        indexed_errors=indexed_errors,
    ):
        return _failed_result(normalized_campaign_ids, indexed_errors=indexed_errors)

    resource_names: list[str] = []
    campaign_errors: list[dict[str, str]] = []
    for index, item in enumerate(results):
        if (error := indexed_errors.get(index)) is not None:
            campaign_errors.append(error)
        else:
            resource_names.append(item["resourceName"])
    return {
        "resource_names": resource_names,
        "campaign_errors": campaign_errors,
    }


def _valid_results(
    results: Any,
    *,
    expected_resource_names: list[str],
    indexed_errors: Mapping[int, dict[str, str]],
) -> bool:
    if not isinstance(results, list) or len(results) != len(expected_resource_names):
        return False
    seen: set[str] = set()
    for index, (item, expected_resource_name) in enumerate(
        zip(results, expected_resource_names, strict=True)
    ):
        if not isinstance(item, Mapping):
            return False
        resource_name = item.get("resourceName")
        if index in indexed_errors:
            if resource_name is not None:
                return False
            continue
        if resource_name != expected_resource_name or resource_name in seen:
            return False
        seen.add(resource_name)
    return True


def _failed_result(
    campaign_ids: list[str],
    *,
    indexed_errors: Mapping[int, dict[str, str]],
) -> dict[str, Any]:
    return {
        "resource_names": [],
        "campaign_errors": [
            _campaign_error(campaign_id, indexed_errors.get(index))
            for index, campaign_id in enumerate(campaign_ids)
        ],
    }


def _campaign_error(campaign_id: str, diagnostic: dict[str, str] | None) -> dict[str, str]:
    return {
        "campaign_id": campaign_id,
        "message": diagnostic["message"] if diagnostic else _UNACCOUNTED_RESPONSE_MESSAGE,
        "error_code": (diagnostic["error_code"] if diagnostic else _UNACCOUNTED_RESPONSE_CODE),
    }
