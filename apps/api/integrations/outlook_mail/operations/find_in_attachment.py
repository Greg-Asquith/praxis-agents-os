# apps/api/integrations/outlook_mail/operations/find_in_attachment.py

"""Finds literal text throughout a supported file attachment and returns bounded excerpts."""

from services.integrations.microsoft_graph import MicrosoftGraphClient
from utils.document_markdown import DocumentConversionError, find_document_text

from .get_attachment import conversion_error, download_readable_attachment
from .utils import untrusted

OPERATION = "find_in_attachment"


async def find_in_attachment(
    client: MicrosoftGraphClient, *, message_id: str, attachment_id: str, query: str, limit: int
) -> dict:
    content_type, filename, data = await download_readable_attachment(
        client, message_id=message_id, attachment_id=attachment_id, operation=OPERATION
    )
    try:
        found = await find_document_text(
            data,
            content_type=content_type,
            filename=filename,
            query=query,
            limit=limit,
            strict_utf8=False,
        )
    except DocumentConversionError:
        raise conversion_error(OPERATION) from None
    return {
        "name": untrusted(message_id, filename),
        "content_type": untrusted(message_id, content_type),
        "total_bytes": found.total_bytes,
        "matches": [
            {"offset": offset, "excerpt": untrusted(message_id, excerpt)}
            for offset, excerpt in found.matches
        ],
        "count": len(found.matches),
        "has_more": found.has_more,
    }
