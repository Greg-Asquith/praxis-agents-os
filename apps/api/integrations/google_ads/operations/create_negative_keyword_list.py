# apps/api/integrations/google_ads/operations/create_negative_keyword_list.py

"""Create Google Ads negative keyword shared sets with duplicate skipping."""

from typing import Any

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import partial_failure_errors, stream_rows


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
    results = payload.get("results", []) if isinstance(payload, dict) else []
    created_names = [
        create_names[index]
        for index, item in enumerate(results)
        if index < len(create_names) and isinstance(item, dict) and item.get("resourceName")
    ]
    resource_names = [
        str(item.get("resourceName"))
        for item in results
        if isinstance(item, dict) and item.get("resourceName")
    ]
    return {
        "created_names": created_names,
        "resource_names": resource_names,
        "skipped_existing": skipped_existing,
        "list_errors": partial_failure_errors(
            payload,
            create_names,
            value_key="name",
            default_message="Negative keyword list creation failed",
        ),
    }
