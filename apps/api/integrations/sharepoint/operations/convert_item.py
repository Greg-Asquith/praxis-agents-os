# apps/api/integrations/sharepoint/operations/convert_item.py

"""Converts a selected file to bounded Markdown for bulk imports."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import (
    DocumentConversionError,
    convert_document_to_markdown_result,
)

from ..settings import sharepoint_settings
from .download_item import download_item
from .utils import (
    conversion_error,
    file_content_metadata,
)


async def convert_item(
    client: MicrosoftGraphClient, *, drive_id: str, item_id: str, max_bytes: int | None = None
) -> dict:
    item, data = await download_item(
        client, drive_id=drive_id, item_id=item_id, operation="read_file"
    )
    result = file_content_metadata(
        item, drive_id=drive_id, size_bytes=len(data), operation="read_file"
    )
    content_type = result["content_type"].content
    try:
        conversion = await convert_document_to_markdown_result(
            data,
            content_type=content_type,
            filename=result["name"].content,
            max_bytes=(
                sharepoint_settings.SHAREPOINT_FILE_MAX_MARKDOWN_BYTES
                if max_bytes is None
                else max_bytes
            ),
            timeout_seconds=30,
            strict_utf8=True,
        )
    except DocumentConversionError:
        raise conversion_error(operation="read_file") from None
    return {
        **result,
        "markdown": conversion.markdown,
        "limit_reached": conversion.truncated,
        "source": conversion.source,
    }
