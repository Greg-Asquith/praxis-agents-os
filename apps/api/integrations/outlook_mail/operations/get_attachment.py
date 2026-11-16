# apps/api/integrations/outlook_mail/operations/get_attachment.py

"""Reads one Markdown window of a supported file attachment."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import DocumentConversionError, read_document_window
from utils.text_window import TextWindowError

from .download_attachment import attachment_error, conversion_error, download_readable_attachment
from .utils import untrusted

MAX_MARKDOWN_BYTES = 64 * 1024
OPERATION = "read_attachment"


async def get_attachment(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str, offset: int = 0
) -> dict:
    content_type, filename, data = await download_readable_attachment(
        client, message_id=message_id, attachment_id=attachment_id, operation=OPERATION
    )
    try:
        conversion = await read_document_window(
            data,
            content_type=content_type,
            filename=filename,
            offset=offset,
            max_bytes=MAX_MARKDOWN_BYTES,
            strict_utf8=False,
        )
    except TextWindowError as exc:
        raise attachment_error(str(exc), "invalid_offset", operation=OPERATION) from None
    except DocumentConversionError:
        raise conversion_error(OPERATION) from None
    window = conversion.window
    truncated = window.end_offset < window.total_bytes
    return {
        "name": untrusted(message_id, filename),
        "content_type": untrusted(message_id, content_type),
        "size_bytes": len(data),
        "markdown": untrusted(message_id, window.content),
        "offset": window.offset,
        "end_offset": window.end_offset,
        "total_bytes": window.total_bytes,
        "truncated": truncated,
        "hint": (
            f"Showing bytes {window.offset}-{window.end_offset} of {window.total_bytes}. "
            "To find specific information, use outlook_mail_find_in_attachment; to keep "
            f"reading in order, call outlook_mail_read_attachment with offset={window.end_offset}."
            if truncated
            else None
        ),
        "source": conversion.source,
    }
