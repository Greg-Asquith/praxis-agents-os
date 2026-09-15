# apps/api/integrations/sharepoint/operations/list_children.py

"""List one bounded page of children from a selected library."""

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .get_item import get_item
from .utils import (
    ITEM_SELECT,
    invalid_response,
    is_local_item,
    item_kind,
    item_path,
    item_result,
    object_payload,
)


async def list_children(
    client: MicrosoftGraphClient, *, drive_id: str, folder_id: str | None = None, limit: int = 50
) -> dict:
    if not 1 <= limit <= 200:
        raise ValueError("SharePoint folder limits must be between 1 and 200.")
    if folder_id is not None:
        folder = await get_item(client, drive_id=drive_id, item_id=folder_id)
        if item_kind(folder, operation="list_folder") != "folder":
            raise IntegrationValidationError(
                "Select a SharePoint folder to list its contents.",
                provider_key="sharepoint",
                operation="list_folder",
                error_code="not_a_folder",
            )
    payload = object_payload(
        await client.get(
            f"{item_path(drive_id, folder_id)}/children",
            operation="list_folder",
            policy=IntegrationRequestPolicy.READ,
            params={"$select": ITEM_SELECT, "$top": limit},
        ),
        operation="list_folder",
    )
    values = payload.get("value")
    if not isinstance(values, list):
        raise invalid_response("list_folder")
    items = [
        item_result(item, drive_id=drive_id, operation="list_folder")
        for item in values[:limit]
        if isinstance(item, dict)
        and is_local_item(item, drive_id)
        and item_kind(item, operation="list_folder") is not None
    ]
    return {
        "items": items,
        "count": len(items),
        "has_more": bool(payload.get("@odata.nextLink")) or len(values) > limit,
    }
