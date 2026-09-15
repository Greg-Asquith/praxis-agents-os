# apps/api/integrations/sharepoint/operations/convert_item.py

"""Read a selected file as bounded Markdown with SharePoint provenance."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import (
    DocumentConversionError,
    convert_document_to_markdown_result,
)

from .download_item import download_item
from .utils import MAX_MARKDOWN_BYTES, file_error, item_result, untrusted


async def convert_item(client: MicrosoftGraphClient, *, drive_id: str, item_id: str) -> dict:
    item, data = await download_item(client, drive_id=drive_id, item_id=item_id)
    result = item_result(item, drive_id=drive_id, operation="read_file")
    content_type = result["content_type"].content
    try:
        conversion = await convert_document_to_markdown_result(
            data,
            content_type=content_type,
            filename=result["name"].content,
            max_bytes=MAX_MARKDOWN_BYTES,
            timeout_seconds=30,
            strict_utf8=True,
        )
    except DocumentConversionError:
        raise file_error(
            "This file could not be converted to text. It may be protected or damaged. "
            "Try an unprotected copy.",
            "conversion_failed",
        ) from None
    return {
        "name": result["name"],
        "content_type": result["content_type"],
        "size_bytes": len(data),
        "modified_at": result["modified_at"],
        "web_url": result["web_url"],
        "markdown": untrusted(drive_id, item_id, conversion.markdown, MAX_MARKDOWN_BYTES),
        "truncated": conversion.truncated,
        "source": conversion.source,
    }
