# apps/api/integrations/outlook_mail/operations/utils.py

"""Bounds and provenance for Outlook provider content."""

from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationValidationError
from services.agents.runtime.untrusted import UntrustedNode

MESSAGE_SELECT = (
    "id,subject,from,toRecipients,receivedDateTime,isRead,hasAttachments,"
    "bodyPreview,importance,inferenceClassification"
)
ATTACHMENT_SELECT = "id,name,contentType,size,isInline"
MAX_BODY_CHARS = 50_000
WELL_KNOWN_FOLDERS = frozenset(
    {"inbox", "drafts", "sentitems", "deleteditems", "archive", "junkemail"}
)


def text(value: object, limit: int = 500) -> str:
    return value[:limit] if isinstance(value, str) else ""


def untrusted(message_id: str, content: str) -> UntrustedNode:
    return UntrustedNode(source_kind="outlook_message", source_ref=message_id, content=content)


def object_payload(value: object, *, operation: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntegrationValidationError(
            "Outlook returned an invalid response",
            provider_key="outlook_mail",
            operation=operation,
        )
    return value


def message_path(message_id: str) -> str:
    return f"/me/messages/{quote(message_id, safe='')}"


def address(value: object, message_id: str) -> dict[str, UntrustedNode]:
    email = value.get("emailAddress") if isinstance(value, dict) else None
    email = email if isinstance(email, dict) else {}
    return {
        "name": untrusted(message_id, text(email.get("name"))),
        "address": untrusted(message_id, text(email.get("address"), 320)),
    }


def received_at(value: object) -> str | None:
    try:
        parsed = datetime.fromisoformat(text(value, 100))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def message_summary(payload: dict[str, Any]) -> dict[str, Any]:
    message_id = text(payload.get("id"), 512)
    recipients = payload.get("toRecipients")
    importance = payload.get("importance")
    return {
        "message_id": message_id,
        "subject": untrusted(message_id, text(payload.get("subject"))),
        "from": address(payload.get("from"), message_id),
        "to_count": len(recipients) if isinstance(recipients, list) else 0,
        "received_at": received_at(payload.get("receivedDateTime")),
        "is_read": payload.get("isRead") is True,
        "has_attachments": payload.get("hasAttachments") is True,
        "preview": untrusted(message_id, text(payload.get("bodyPreview"), 255)),
        "importance": importance if importance in {"low", "normal", "high"} else "normal",
        "focused": payload.get("inferenceClassification") == "focused",
    }


class _BodyText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"br", "p", "div", "li"}:
            self.parts.append("\n")


def body_text(value: object) -> tuple[str, bool]:
    body = value if isinstance(value, dict) else {}
    content = body.get("content")
    content = content if isinstance(content, str) else ""
    if text(body.get("contentType")).lower() == "html":
        parser = _BodyText()
        parser.feed(content)
        content = "".join(parser.parts)
    return content[:MAX_BODY_CHARS], len(content) > MAX_BODY_CHARS
