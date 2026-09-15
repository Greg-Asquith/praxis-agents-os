# apps/api/integrations/sharepoint/operations/get_item.py

"""Read metadata for one item in a selected drive."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import ITEM_SELECT, invalid_response, is_local_item, item_path, object_payload


async def get_item(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str, include_download_url: bool = False
) -> dict:
    select = ITEM_SELECT
    if include_download_url:
        select += ",@microsoft.graph.downloadUrl"
    payload = object_payload(
        await client.get(
            item_path(drive_id, item_id),
            operation="get_item",
            policy=IntegrationRequestPolicy.READ,
            # Graph can omit download annotations when metadata fields use $select.
            params=None if include_download_url else {"$select": select},
        ),
        operation="get_item",
    )
    if payload.get("id") != item_id or not is_local_item(payload, drive_id):
        raise invalid_response("get_item")
    return {key: payload[key] for key in select.split(",") if key in payload}
