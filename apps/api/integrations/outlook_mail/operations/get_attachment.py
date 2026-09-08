# apps/api/integrations/outlook_mail/operations/get_attachment.py

"""Converts one supported file attachment within download and output limits."""

from urllib.parse import quote

from core.exceptions.integration import IntegrationDownloadTooLargeError, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import (
    TRUNCATION_MARKER,
    DocumentConversionError,
    convert_document_to_markdown,
    document_content_type,
)

from ..settings import outlook_mail_settings
from .utils import ATTACHMENT_SELECT, message_path, object_payload, text, untrusted

MAX_MARKDOWN_BYTES = 64 * 1024


async def get_attachment(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str
) -> dict:
    path = f"{message_path(message_id)}/attachments/{quote(attachment_id, safe='')}"
    metadata = object_payload(
        await client.get(
            path,
            operation="read_attachment",
            policy=IntegrationRequestPolicy.READ,
            params={"$select": ATTACHMENT_SELECT},
        ),
        operation="read_attachment",
    )
    if metadata.get("@odata.type") != "#microsoft.graph.fileAttachment":
        raise _attachment_error("This attachment is not a file.", "unsupported_attachment_kind")
    content_type = document_content_type(text(metadata.get("contentType"), 255))
    if content_type is None:
        raise _attachment_error(
            "This attachment type cannot be read as text.", "unsupported_attachment_type"
        )
    size = metadata.get("size")
    if type(size) is not int or size < 0:
        raise _attachment_error(
            "Outlook returned an invalid attachment size.", "invalid_attachment_size"
        )
    if size > outlook_mail_settings.OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES:
        raise _attachment_error(
            "This attachment exceeds the download limit.", "attachment_too_large"
        )
    try:
        data = await client.get_graph_bytes(
            f"{path}/$value",
            operation="read_attachment",
            max_bytes=outlook_mail_settings.OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES,
        )
    except IntegrationDownloadTooLargeError as exc:
        raise IntegrationValidationError(
            "This attachment exceeds the download limit.",
            provider_key="outlook_mail",
            operation="read_attachment",
            error_code="attachment_too_large",
            failure_disposition=exc.failure_disposition,
        ) from None
    filename = text(metadata.get("name"))
    try:
        markdown = await convert_document_to_markdown(
            data,
            content_type=content_type,
            filename=filename,
            max_bytes=MAX_MARKDOWN_BYTES,
        )
    except DocumentConversionError:
        raise _attachment_error(
            "This attachment could not be converted to text.", "attachment_conversion_failed"
        ) from None
    return {
        "name": untrusted(message_id, filename),
        "content_type": untrusted(message_id, content_type),
        "size_bytes": len(data),
        "markdown": untrusted(message_id, markdown),
        "truncated": markdown.endswith(TRUNCATION_MARKER),
        "source": "text"
        if content_type in {"text/plain", "text/markdown", "text/csv", "application/json"}
        else "converted",
    }


def _attachment_error(message: str, code: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        message, provider_key="outlook_mail", operation="read_attachment", error_code=code
    )
