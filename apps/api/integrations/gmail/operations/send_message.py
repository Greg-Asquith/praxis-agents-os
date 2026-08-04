# apps/api/integrations/gmail/operations/send_message.py

"""Send one rich HTML Gmail message with a derived plain-text alternative."""

import base64
import re
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any

from integrations.gmail.client import GmailClient
from services.integrations.previews.sanitize import sanitize_preview_html

_SKIP_TAGS = {"head", "script", "style", "title"}
_BLOCK_TAGS = {
    "article",
    "blockquote",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "ol",
    "p",
    "section",
    "table",
    "tr",
    "ul",
}


class _PlainTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._href: str | None = None
        self._anchor_start = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            self._href = next((value for name, value in attrs if name == "href"), None)
            self._anchor_start = len(self.parts)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")
        elif tag == "a" and self._href:
            text = "".join(self.parts[self._anchor_start :]).strip()
            if self._href not in (text, f"mailto:{text}"):
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Derive the plain-text alternative sent alongside the HTML body."""
    extractor = _PlainTextExtractor()
    extractor.feed(html)
    extractor.close()
    flattened = "".join(extractor.parts).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in flattened.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


async def send_message(
    client: GmailClient,
    *,
    to: list[str],
    subject: str,
    body_html: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> dict[str, Any]:
    html = sanitize_preview_html(body_html)
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    message.set_content(html_to_text(html))
    message.add_alternative(html, subtype="html")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    payload = await client.post(
        "users/me/messages/send",
        operation="send_message",
        json={"raw": raw},
    )
    return {"message_id": str(payload.get("id", ""))}
