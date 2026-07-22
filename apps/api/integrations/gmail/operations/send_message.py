# apps/api/integrations/gmail/operations/send_message.py

"""Send one plain-text Gmail message."""

import base64
from email.message import EmailMessage
from typing import Any

from integrations.gmail.client import GmailClient


async def send_message(
    client: GmailClient,
    *,
    to: list[str],
    subject: str,
    body_text: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict[str, Any]:
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    message.set_content(body_text)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    payload = await client.post(
        "users/me/messages/send",
        operation="send_message",
        json={"raw": raw},
    )
    return {"message_id": str(payload.get("id", ""))}
