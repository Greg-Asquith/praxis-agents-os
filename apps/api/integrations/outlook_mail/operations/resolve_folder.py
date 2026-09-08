# apps/api/integrations/outlook_mail/operations/resolve_folder.py

"""Resolves a well-known folder or exact display name before use."""

from core.exceptions.integration import IntegrationNotFoundError
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .list_mail_folders import list_mail_folders
from .utils import WELL_KNOWN_FOLDERS


async def resolve_folder(client: MicrosoftGraphClient, *, folder: str) -> str:
    if folder in WELL_KNOWN_FOLDERS:
        return folder
    for item in await list_mail_folders(client):
        if item.get("displayName") == folder and isinstance(item.get("id"), str) and item["id"]:
            return item["id"]
    raise IntegrationNotFoundError(
        "Outlook folder was not found. Choose a folder returned by the folder list.",
        provider_key="outlook_mail",
        operation="resolve_folder",
        error_code="folder_not_found",
    )
