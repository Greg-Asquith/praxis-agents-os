# apps/api/integrations/outlook_mail/operations/get_attachment.py

"""Converts one supported file attachment within download and output limits."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import (
    DocumentConversionError,
    convert_document_to_markdown_result,
    document_content_type,
)

from ..settings import outlook_mail_settings
from .download_attachment import attachment_error, attachment_metadata, download_attachment
from .utils import text, untrusted

MAX_MARKDOWN_BYTES = 64 * 1024
OPERATION = "read_attachment"


async def get_attachment(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str
) -> dict:
    metadata = await attachment_metadata(
        client, message_id=message_id, attachment_id=attachment_id, operation=OPERATION
    )
    content_type = document_content_type(text(metadata.get("contentType"), 255))
    if content_type is None:
        raise attachment_error(
            "This attachment type cannot be read as text.",
            "unsupported_attachment_type",
            operation=OPERATION,
        )
    data = await download_attachment(
        client,
        message_id=message_id,
        attachment_id=attachment_id,
        size=metadata["size"],
        max_bytes=outlook_mail_settings.OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES,
        operation=OPERATION,
    )
    filename = text(metadata.get("name"))
    try:
        conversion = await convert_document_to_markdown_result(
            data,
            content_type=content_type,
            filename=filename,
            max_bytes=MAX_MARKDOWN_BYTES,
        )
    except DocumentConversionError:
        raise attachment_error(
            "This attachment could not be converted to text.",
            "attachment_conversion_failed",
            operation=OPERATION,
        ) from None
    return {
        "name": untrusted(message_id, filename),
        "content_type": untrusted(message_id, content_type),
        "size_bytes": len(data),
        "markdown": untrusted(message_id, conversion.markdown),
        "truncated": conversion.truncated,
        "source": conversion.source,
    }
