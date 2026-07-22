# apps/api/integrations/gmail/operations/read_message.py

"""Read and decode one Gmail message."""

from html.parser import HTMLParser
from typing import Any

from integrations.gmail.client import GmailClient
from integrations.gmail.operations.utils import extract_headers, untrusted
from utils.decode import decode_base64url

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
    html_body = _extract_body(payload.get("payload") if isinstance(payload, dict) else None, True)
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
        "raw_html_body": html_body,
        "truncated": truncated,
    }


def _extract_body(payload: Any, html: bool = False) -> str:
    plain = _find_part(payload, "text/plain")
    if plain is not None:
        return plain
    html = _find_part(payload, "text/html")
    if html is None:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    return "".join(parser.parts)


def _find_part(part: Any, media_type: str) -> str | None:
    if not isinstance(part, dict):
        return None
    if part.get("mimeType") == media_type:
        body = part.get("body")
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, str):
            return decode_base64url(data)
    children = part.get("parts")
    if isinstance(children, list):
        for child in children:
            value = _find_part(child, media_type)
            if value is not None:
                return value
    return None
