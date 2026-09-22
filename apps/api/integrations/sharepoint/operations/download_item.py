# apps/api/integrations/sharepoint/operations/download_item.py

"""Downloads one supported file without exposing its pre-authenticated URL."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import document_content_type

from ..settings import sharepoint_settings
from .download_utils import download_content, download_metadata
from .utils import file_error


async def download_item(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str, operation: str = "read_file"
) -> tuple[dict, bytes]:
    item, url = await download_metadata(
        client,
        drive_id=drive_id,
        item_id=item_id,
        operation=operation,
        unsupported_message="Select a file to read. Folders and packages cannot be read.",
    )
    content_type = document_content_type(item["file"].get("mimeType"))
    if content_type is None:
        raise file_error(
            "This file type cannot be read as text. Select a document or text file.",
            "unsupported_type",
            operation=operation,
        )
    data = await download_content(
        client,
        item=item,
        url=url,
        operation=operation,
        max_bytes=sharepoint_settings.SHAREPOINT_FILE_MAX_DOWNLOAD_BYTES,
        content_type=content_type,
        too_large_message="This file exceeds the download limit. Select a smaller file.",
    )
    return item, data
