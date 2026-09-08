# apps/api/integrations/outlook_mail/operations/get_message.py

"""Reads bounded message text and attachment metadata."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import (
    ATTACHMENT_SELECT,
    MESSAGE_SELECT,
    address,
    body_text,
    message_path,
    message_summary,
    object_payload,
    text,
    untrusted,
)


async def get_message(client: MicrosoftGraphClient, *, message_id: str) -> dict:
    path = message_path(message_id)
    payload = object_payload(
        await client.get(
            path,
            operation="read_message",
            policy=IntegrationRequestPolicy.READ,
            params={
                "$select": f"{MESSAGE_SELECT},ccRecipients,body,conversationId,internetMessageId,webLink"
            },
            headers={"Prefer": 'outlook.body-content-type="text"'},
        ),
        operation="read_message",
    )
    attachments = await client.paginate(
        f"{path}/attachments",
        operation="read_message",
        params={"$select": ATTACHMENT_SELECT, "$top": 50},
        max_items=50,
        max_pages=5,
    )
    body, truncated = body_text(payload.get("body"))
    result = message_summary({**payload, "id": message_id})
    result.update(
        body=untrusted(message_id, body),
        truncated=truncated,
        attachments=[
            {
                "attachment_id": text(item.get("id"), 512),
                "name": untrusted(message_id, text(item.get("name"))),
                "content_type": untrusted(message_id, text(item.get("contentType"), 255)),
                "size_bytes": item.get("size", 0),
                "is_inline": item.get("isInline") is True,
            }
            for item in attachments
        ],
        conversation_id=untrusted(message_id, text(payload.get("conversationId"), 512)),
        internet_message_id=untrusted(message_id, text(payload.get("internetMessageId"), 1000)),
        web_link=untrusted(message_id, text(payload.get("webLink"), 2000)),
    )
    for field, key in (("to", "toRecipients"), ("cc", "ccRecipients")):
        values = payload.get(key)
        result[field] = (
            [address(value, message_id) for value in values[:50]]
            if isinstance(values, list)
            else []
        )
    return result
