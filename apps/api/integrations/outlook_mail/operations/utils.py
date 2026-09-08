# apps/api/integrations/outlook_mail/operations/utils.py

"""Bounds and provenance for Outlook provider content."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.http import IntegrationRequestPolicy

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


@dataclass
class MailWriteState:
    """Retains confirmed effects if a later request fails or is cancelled."""

    message_id: str | None = None
    web_link: str | None = None
    step: str = "draft"
    applied_steps: list[str] = field(default_factory=list)

    def created(self, payload: object) -> None:
        message_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 512:
            raise IntegrationValidationError(
                "Outlook did not return the message reference.",
                provider_key="outlook_mail",
                operation=self.step,
                failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
                error_code="invalid_message_response",
            )
        self.message_id = message_id
        self.web_link = text(payload.get("webLink"), 2_000) or None
        self.applied_steps.append(self.step)


def graph_recipients(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": value}} for value in addresses]


async def reject_draft_attachments(client, *, message_id: str, operation: str) -> None:
    """Rejects attachments and incomplete attachment collections before sending."""
    # hasAttachments excludes inline attachments, so inspect the collection too.
    attachments = await client.get(
        f"{message_path(message_id)}/attachments",
        operation=operation,
        policy=IntegrationRequestPolicy.READ,
        params={"$select": "id", "$top": 1},
    )
    if (
        not isinstance(attachments, dict)
        or attachments.get("value") != []
        or "@odata.nextLink" in attachments
    ):
        raise IntegrationValidationError(
            "Send drafts with attachments in Outlook.",
            provider_key="outlook_mail",
            operation=operation,
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            error_code="draft_attachments_unsupported",
        )
