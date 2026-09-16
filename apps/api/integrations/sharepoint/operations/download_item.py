# apps/api/integrations/sharepoint/operations/download_item.py

"""Download one supported file without exposing its pre-authenticated URL."""

from core.exceptions.integration import IntegrationDownloadTooLargeError
from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import document_content_type

from ..settings import sharepoint_settings
from .get_item import get_item
from .utils import file_error, invalid_response, item_kind, item_result, require_file_citation


async def download_item(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str, operation: str = "read_file"
) -> tuple[dict, bytes]:
    item = await get_item(client, drive_id=drive_id, item_id=item_id, include_download_url=True)
    url = item.pop("@microsoft.graph.downloadUrl", None)
    if item_kind(item, operation=operation) != "file":
        raise file_error(
            "Select a file to read. Folders and packages cannot be read.",
            "unsupported_type",
            operation=operation,
        )
    result = item_result(item, drive_id=drive_id, operation=operation)
    require_file_citation(item.get("webUrl"), operation=operation)
    content_type = document_content_type(result["content_type"].content)
    if content_type is None:
        raise file_error(
            "This file type cannot be read as text. Select a document or text file.",
            "unsupported_type",
            operation=operation,
        )
    if "size" not in item:
        raise invalid_response(operation)
    max_bytes = sharepoint_settings.SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES
    if result["size_bytes"] > max_bytes:
        raise file_error(
            "This file exceeds the download limit. Select a smaller file.",
            "too_large",
            operation=operation,
        )
    if not isinstance(url, str) or not url:
        raise invalid_response(operation)
    try:
        data = await client.get_bytes(url, operation=operation, max_bytes=max_bytes)
    except IntegrationDownloadTooLargeError:
        raise file_error(
            "This file exceeds the download limit. Select a smaller file.",
            "too_large",
            operation=operation,
        ) from None
    item["file"] = {"mimeType": content_type}
    return item, data
