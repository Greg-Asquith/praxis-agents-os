# apps/api/integrations/outlook_mail/operations/get_attachment.py

"""Reads one Markdown window of a supported file attachment."""

from core.exceptions.integration import IntegrationValidationError
from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import (
    DocumentConversionError,
    document_content_type,
    read_document_window,
)
from utils.text_window import TextWindowError

from ..settings import outlook_mail_settings
from .download_attachment import attachment_error, attachment_metadata, download_attachment
from .utils import text, untrusted

MAX_MARKDOWN_BYTES = 64 * 1024
OPERATION = "read_attachment"


async def download_readable_attachment(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str, operation: str
) -> tuple[str, str, bytes]:
    """Returns the content type, name, and bytes of an attachment that converts to Markdown."""
    metadata = await attachment_metadata(
        client, message_id=message_id, attachment_id=attachment_id, operation=operation
    )
    content_type = document_content_type(text(metadata.get("contentType"), 255))
    if content_type is None:
        raise attachment_error(
            "This attachment type cannot be read as text.",
            "unsupported_attachment_type",
            operation=operation,
        )
    data = await download_attachment(
        client,
        message_id=message_id,
        attachment_id=attachment_id,
        size=metadata["size"],
        max_bytes=outlook_mail_settings.OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES,
        operation=operation,
    )
    return content_type, text(metadata.get("name")), data


def conversion_error(operation: str) -> IntegrationValidationError:
    return attachment_error(
        "This attachment could not be converted to text.",
        "attachment_conversion_failed",
        operation=operation,
    )


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
