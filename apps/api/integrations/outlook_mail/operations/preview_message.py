# apps/api/integrations/outlook_mail/operations/preview_message.py

"""Fetches raw message content for engine-owned preview sanitisation."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import graph_client_for_connection
from services.integrations.plugin import IntegrationPreviewPayload

from .utils import message_path, object_payload, text


async def fetch_message_preview(db, connection, ref: str) -> IntegrationPreviewPayload:
    client = graph_client_for_connection(db, connection, expected_provider_key="outlook_mail")
    payload = object_payload(
        await client.get(
            message_path(ref),
            operation="preview_message",
            policy=IntegrationRequestPolicy.READ,
            params={
                "$select": "body,subject,from,toRecipients,ccRecipients,receivedDateTime,parentFolderId,hasAttachments"
            },
        ),
        operation="preview_message",
    )
    body = payload.get("body")
    body = body if isinstance(body, dict) else {}
    meta = {
        "subject": text(payload.get("subject")),
        "received_at": text(payload.get("receivedDateTime"), 100),
        "folder": text(payload.get("parentFolderId"), 512),
        "has_attachments": payload.get("hasAttachments") is True,
    }
    for key, source in (("from", "from"), ("to", "toRecipients"), ("cc", "ccRecipients")):
        values = payload.get(source)
        values = values if isinstance(values, list) else [values]
        addresses = []
        for item in values[:50]:
            email = item.get("emailAddress") if isinstance(item, dict) else None
            if isinstance(email, dict):
                addresses.append(text(email.get("address"), 320))
        meta[key] = ", ".join(addresses)
    return IntegrationPreviewPayload(
        content_type="html" if text(body.get("contentType")).lower() == "html" else "text",
        content=body.get("content") if isinstance(body.get("content"), str) else "",
        meta=meta,
    )
