# apps/api/integrations/sharepoint/operations/find_in_item.py

"""Find literal text throughout a selected file and return bounded excerpts."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import DocumentConversionError, find_document_text

from .download_item import download_item
from .utils import conversion_error, file_content_metadata, untrusted


async def find_in_item(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str, query: str, limit: int
) -> dict:
    item, data = await download_item(
        client, drive_id=drive_id, item_id=item_id, operation="find_in_file"
    )
    metadata = file_content_metadata(
        item, drive_id=drive_id, size_bytes=len(data), operation="find_in_file"
    )
    try:
        found = await find_document_text(
            data,
            content_type=metadata["content_type"].content,
            filename=metadata["name"].content,
            query=query,
            limit=limit,
            timeout_seconds=30,
        )
    except DocumentConversionError:
        raise conversion_error(operation="find_in_file") from None
    return {
        "name": metadata["name"],
        "web_url": metadata["web_url"],
        "total_bytes": found.total_bytes,
        "limit_reached": False,
        "matches": [
            {"offset": offset, "excerpt": untrusted(drive_id, item_id, excerpt, 440)}
            for offset, excerpt in found.matches
        ],
        "count": len(found.matches),
        "has_more": found.has_more,
    }
