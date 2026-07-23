# apps/api/integrations/gmail/operations/read_message.py

"""Read and decode one Gmail message."""

from html.parser import HTMLParser
from typing import Any

from integrations.gmail.client import GmailClient
from integrations.gmail.operations.utils import extract_headers, find_body_part, untrusted

MAX_BODY_CHARS = 50_000
TRUNCATION_MARKER = "\n\n[Message body truncated at 50000 characters.]"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


async def read_message(client: GmailClient, *, message_id: str) -> dict[str, Any]:
    payload = await client.get(
        f"users/me/messages/{message_id}",
        operation="read_message",
        params={"format": "full"},
    )
    headers = extract_headers(payload)
    body = _extract_body(payload.get("payload") if isinstance(payload, dict) else None)
    truncated = len(body) > MAX_BODY_CHARS
    if truncated:
        body = f"{body[:MAX_BODY_CHARS]}{TRUNCATION_MARKER}"
    return {
        "message_id": message_id,
        "sender": untrusted(message_id, headers.get("from", "")),
        "to": untrusted(message_id, headers.get("to", "")),
        "subject": untrusted(message_id, headers.get("subject", "")),
        "date": untrusted(message_id, headers.get("date", "")),
        "body": untrusted(message_id, body),
        "truncated": truncated,
    }


def _extract_body(payload: Any) -> str:
    plain = find_body_part(payload, "text/plain")
    if plain is not None:
        return plain
    html = find_body_part(payload, "text/html")
    if html is None:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    return "".join(parser.parts)
