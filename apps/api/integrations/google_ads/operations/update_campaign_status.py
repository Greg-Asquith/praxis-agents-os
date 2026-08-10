# apps/api/integrations/google_ads/operations/update_campaign_status.py

"""Update only campaign status and surface partial failures per campaign."""

from typing import Any, Literal

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import partial_failure_errors


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
        "campaign_errors": partial_failure_errors(
            payload,
            normalized_campaign_ids,
            value_to_error_fields=lambda campaign_id: {"campaign_id": campaign_id},
            unattributed_error_fields={"campaign_id": ""},
            default_message="Campaign update failed",
        ),
    }
