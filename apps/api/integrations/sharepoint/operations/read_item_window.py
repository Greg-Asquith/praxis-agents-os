# apps/api/integrations/sharepoint/operations/read_item_window.py

"""Reads character-aligned Markdown windows from a selected file."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import (
    DocumentConversionError,
    read_document_window,
)
from utils.text_window import TextWindowError

from .download_item import download_item
from .utils import (
    MAX_MARKDOWN_BYTES,
    conversion_error,
    file_content_metadata,
    file_error,
    untrusted,
)
from .write_utils import item_version


async def read_item_window(
    client: MicrosoftGraphClient,
    *,
    drive_id: str,
    item_id: str,
    offset: int = 0,
    max_bytes: int = MAX_MARKDOWN_BYTES,
) -> dict:
    item, data = await download_item(
        client, drive_id=drive_id, item_id=item_id, operation="read_file"
    )
    result = file_content_metadata(
        item, drive_id=drive_id, size_bytes=len(data), operation="read_file"
    )
    try:
        conversion = await read_document_window(
            data,
            content_type=result["content_type"].content,
            filename=result["name"].content,
            offset=offset,
            max_bytes=max_bytes,
            timeout_seconds=30,
        )
    except TextWindowError as exc:
        raise file_error(str(exc), "invalid_offset", operation="read_file") from None
    except DocumentConversionError:
        raise conversion_error(operation="read_file") from None
    window = conversion.window
    result.update(
        version=item_version(item, operation="read_file"),
        source=conversion.source,
        limit_reached=False,
        markdown=untrusted(drive_id, item_id, window.content, max_bytes),
        offset=window.offset,
        end_offset=window.end_offset,
        total_bytes=window.total_bytes,
        truncated=window.end_offset < window.total_bytes,
    )
    if result["truncated"]:
        result["hint"] = (
            f"Showing bytes {offset}-{window.end_offset} of {window.total_bytes}; "
            f"call sharepoint_read_file again with offset={window.end_offset}, "
            "or use sharepoint_find_in_file to jump to specific text."
        )
    return result
