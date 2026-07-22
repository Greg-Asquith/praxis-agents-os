# apps/api/integrations/google_ads/operations/update_campaign_status.py

"""Update only campaign status and surface partial failures per campaign."""

from typing import Any, Literal

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import operation_index


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
    results = payload.get("results", []) if isinstance(payload, dict) else []
    resource_names = [
        str(item.get("resourceName"))
        for item in results
        if isinstance(item, dict) and item.get("resourceName")
    ]
    return {
        "resource_names": resource_names,
        "campaign_errors": _partial_failure_errors(payload, normalized_campaign_ids),
    }


def _partial_failure_errors(payload: Any, campaign_ids: list[str]) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        return []
    partial = payload.get("partialFailureError")
    if not isinstance(partial, dict):
        return []
    errors: list[dict[str, str]] = []
    for detail in partial.get("details", []):
        if not isinstance(detail, dict):
            continue
        for item in detail.get("errors", []):
            if not isinstance(item, dict):
                continue
            location = item.get("location", {})
            index = operation_index(location)
            campaign_id = (
                campaign_ids[index] if index is not None and index < len(campaign_ids) else ""
            )
            errors.append(
                {
                    "campaign_id": campaign_id,
                    "message": str(item.get("message", "Campaign update failed")),
                    "error_code": str(item.get("errorCode", "unknown")),
                }
            )
    if not errors and partial.get("message"):
        errors.append(
            {
                "campaign_id": "",
                "message": str(partial["message"]),
                "error_code": str(partial.get("code", "unknown")),
            }
        )
    return errors
