# apps/api/integrations/outlook_mail/operations/list_messages.py

"""Lists recent messages with bounded folder queries."""

from urllib.parse import quote

from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import MESSAGE_SELECT


async def list_messages(
    client: MicrosoftGraphClient, *, folder_id: str, unread_only: bool, limit: int
) -> list[dict]:
    params = {"$select": MESSAGE_SELECT, "$top": limit, "$orderby": "receivedDateTime desc"}
    if unread_only:
        # Graph requires the sort property before other filter properties.
        params["$filter"] = "receivedDateTime ge 0001-01-01T00:00:00Z and isRead eq false"
    return await client.paginate(
        f"/me/mailFolders/{quote(folder_id, safe='')}/messages",
        operation="search_messages",
        params=params,
        max_items=limit,
        max_pages=5,
    )
