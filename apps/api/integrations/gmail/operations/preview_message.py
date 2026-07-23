# apps/api/integrations/gmail/operations/preview_message.py

"""Fetch one Gmail message for the operator-facing preview surface.

Returns RAW provider HTML plus display metadata; sanitization is engine-owned
in the preview service so a provider can never opt out of it.
"""

from typing import Any

from integrations.gmail.client import GmailClient
from integrations.gmail.operations.count_thread_messages import count_thread_messages
from integrations.gmail.operations.resolve_label_names import resolve_label_names
from integrations.gmail.operations.utils import extract_headers, find_body_part


async def preview_message(client: GmailClient, *, message_id: str) -> dict[str, Any]:
    payload = await client.get(
        f"users/me/messages/{message_id}",
        operation="preview_message",
        params={"format": "full"},
    )
    if not isinstance(payload, dict):
        payload = {}
    headers = extract_headers(payload)
    body_payload = payload.get("payload")
    html = find_body_part(body_payload, "text/html")
    text = find_body_part(body_payload, "text/plain")
    content_type = "html" if html is not None else "text"
    content = html if html is not None else (text or "")

    labels = await resolve_label_names(client, label_ids=payload.get("labelIds"))
    thread_id = payload.get("threadId")
    thread_message_count = await count_thread_messages(client, thread_id=thread_id)

    return {
        "content_type": content_type,
        "content": content,
        "meta": {
            "message_id": message_id,
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "labels": labels,
            "thread_message_count": thread_message_count,
        },
    }
