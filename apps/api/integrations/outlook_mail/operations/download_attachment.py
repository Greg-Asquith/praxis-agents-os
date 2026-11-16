# apps/api/integrations/outlook_mail/operations/download_attachment.py

"""Validates Outlook file attachment metadata and downloads bounded original bytes."""

from urllib.parse import quote

from core.exceptions.integration import IntegrationDownloadTooLargeError, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import document_content_type

from ..settings import outlook_mail_settings
from .utils import ATTACHMENT_SELECT, message_path, object_payload, text

TOO_LARGE_MESSAGE = "This attachment is too large. Ask the sender for a smaller file or a link."


def attachment_path(message_id: str, attachment_id: str) -> str:
    return f"{message_path(message_id)}/attachments/{quote(attachment_id, safe='')}"


async def attachment_metadata(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str, operation: str
) -> dict:
    """Returns metadata for a file attachment with a valid declared size."""
    metadata = object_payload(
        await client.get(
            attachment_path(message_id, attachment_id),
            operation=operation,
            policy=IntegrationRequestPolicy.READ,
            params={"$select": ATTACHMENT_SELECT},
        ),
        operation=operation,
    )
    if metadata.get("@odata.type") != "#microsoft.graph.fileAttachment":
        raise attachment_error(
            "Only file attachments are supported. Embedded emails and linked files are not.",
            "unsupported_attachment_kind",
            operation=operation,
        )
    size = metadata.get("size")
    if type(size) is not int or size < 0:
        raise attachment_error(
            "Outlook returned an invalid attachment size.",
            "invalid_attachment_size",
            operation=operation,
        )
    return metadata


async def download_attachment(
    client: MicrosoftGraphClient,
    *,
    message_id: str,
    attachment_id: str,
    size: int,
    max_bytes: int,
    operation: str,
) -> bytes:
    """Downloads raw bytes, enforcing the limit on declared and streamed sizes."""
    if size > max_bytes:
        raise attachment_error(TOO_LARGE_MESSAGE, "attachment_too_large", operation=operation)
    try:
        return await client.get_graph_bytes(
            f"{attachment_path(message_id, attachment_id)}/$value",
            operation=operation,
            max_bytes=max_bytes,
        )
    except IntegrationDownloadTooLargeError as exc:
        raise IntegrationValidationError(
            TOO_LARGE_MESSAGE,
            provider_key="outlook_mail",
            operation=operation,
            error_code="attachment_too_large",
            failure_disposition=exc.failure_disposition,
        ) from None


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


def attachment_error(message: str, code: str, *, operation: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        message, provider_key="outlook_mail", operation=operation, error_code=code
    )
