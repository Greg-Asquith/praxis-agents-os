# apps/api/integrations/sharepoint/operations/resolve_link.py

"""Resolves one file link and admits only items in selected libraries."""

from base64 import urlsafe_b64encode

from core.exceptions.integration import IntegrationNotFoundError, IntegrationPermissionError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .link_utils import direct_link_path, library_not_selected, link_error
from .utils import ITEM_SELECT, invalid_response, is_local_item, item_result, object_payload


async def resolve_link(client: MicrosoftGraphClient, *, url: str, drives: dict[str, str]) -> dict:
    direct = direct_link_path(url, drives)
    if direct:
        path = direct[1]
    else:
        encoded = "u!" + urlsafe_b64encode(url.encode()).decode().rstrip("=")
        path = f"/shares/{encoded}/driveItem"
    try:
        item = object_payload(
            await client.get(
                path,
                operation="open_link",
                policy=IntegrationRequestPolicy.READ,
                params={"$select": ITEM_SELECT + ",sharepointIds"},
            ),
            operation="open_link",
        )
    except IntegrationNotFoundError:
        raise link_error(
            "The linked file was not found. Check the link and try again.", "not_found"
        ) from None
    except IntegrationPermissionError:
        if not direct:
            raise link_error(
                "This connection cannot resolve that sharing link. Use the file's direct URL.",
                "link_not_supported",
            ) from None
        raise link_error(
            "SharePoint denied access to this file. Check your access in SharePoint.",
            "access_denied",
        ) from None
    parent = object_payload(item.get("parentReference"), operation="open_link")
    drive_id = parent.get("driveId")
    if not isinstance(drive_id, str) or not is_local_item(item, drive_id):
        raise invalid_response("open_link")
    if drive_id not in drives:
        raise library_not_selected(item)
    if direct and drive_id != direct[0]:
        raise invalid_response("open_link")
    return item_result(item, drive_id=drive_id, operation="open_link")
