# apps/api/integrations/outlook_mail/operations/search_messages.py

"""Searches a folder with bounded KQL or a recent-message listing."""

import json
from urllib.parse import quote

from services.integrations.microsoft_graph import MicrosoftGraphClient

from .list_messages import list_messages
from .resolve_folder import resolve_folder
from .utils import MESSAGE_SELECT, message_summary


async def search_messages(
    client: MicrosoftGraphClient,
    *,
    query: str | None = None,
    folder: str = "inbox",
    unread_only: bool = False,
    limit: int = 10,
) -> list[dict]:
    if not 1 <= limit <= 25 or (query is not None and len(query) > 500):
        raise ValueError("Outlook search requires a limit of 1-25 and a query up to 500 characters")
    folder_id = await resolve_folder(client, folder=folder)
    if query and query.strip():
        fetch_limit = 2 * limit if unread_only else limit
        messages = await client.paginate(
            f"/me/mailFolders/{quote(folder_id, safe='')}/messages",
            operation="search_messages",
            params={
                "$select": MESSAGE_SELECT,
                "$top": fetch_limit,
                "$search": json.dumps(query, ensure_ascii=False),
            },
            max_items=fetch_limit,
            max_pages=5,
        )
        if unread_only:
            messages = [message for message in messages if message.get("isRead") is False]
    else:
        messages = await list_messages(
            client, folder_id=folder_id, unread_only=unread_only, limit=limit
        )
    return [message_summary(message) for message in messages[:limit]]
