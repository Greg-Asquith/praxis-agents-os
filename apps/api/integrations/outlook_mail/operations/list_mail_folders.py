# apps/api/integrations/outlook_mail/operations/list_mail_folders.py

"""Lists bounded top-level Outlook mail folders."""

from services.integrations.microsoft_graph import MicrosoftGraphClient


async def list_mail_folders(client: MicrosoftGraphClient) -> list[dict]:
    return await client.paginate(
        "/me/mailFolders",
        operation="list_mail_folders",
        params={
            "$select": "id,displayName,unreadItemCount,totalItemCount,childFolderCount",
            "$top": 200,
        },
        max_items=200,
        max_pages=10,
    )
