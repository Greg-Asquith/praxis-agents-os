# apps/api/integrations/outlook_mail/operations/copy_attachment.py

"""Downloads original attachment bytes accepted by the workspace file contract."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from core.exceptions.general import AppValidationError
from services.files.contract import contract_for_content_type, max_size_bytes
from services.integrations.microsoft_graph import MicrosoftGraphClient

from ..settings import outlook_mail_settings
from .download_attachment import attachment_error, attachment_metadata, download_attachment
from .utils import text

OPERATION = "save_attachment"


@dataclass(frozen=True)
class AttachmentCopy:
    name: str
    content_type: str
    content: bytes


async def copy_attachment(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str
) -> AttachmentCopy:
    """Rejects unsupported or mislabelled attachments before downloading any bytes."""
    metadata = await attachment_metadata(
        client, message_id=message_id, attachment_id=attachment_id, operation=OPERATION
    )
    try:
        contract = contract_for_content_type(text(metadata.get("contentType"), 255))
    except AppValidationError:
        raise attachment_error(
            "Files does not support this attachment type. "
            "Save a supported document, image, video, or audio file.",
            "unsupported_attachment_type",
            operation=OPERATION,
        ) from None
    name = text(metadata.get("name"), 255).strip() or "Outlook attachment"
    extension = PurePosixPath(name).suffix.lower()
    if extension and extension not in contract.extensions:
        raise attachment_error(
            "This attachment's name does not match its file type, so it cannot be saved.",
            "attachment_type_mismatch",
            operation=OPERATION,
        )
    content = await download_attachment(
        client,
        message_id=message_id,
        attachment_id=attachment_id,
        size=metadata["size"],
        max_bytes=min(
            outlook_mail_settings.OUTLOOK_MAIL_ATTACHMENT_MAX_BYTES, max_size_bytes(contract)
        ),
        operation=OPERATION,
    )
    return AttachmentCopy(name=name, content_type=contract.content_type, content=content)
