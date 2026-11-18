# apps/api/integrations/gmail/operations/send_merge_message.py

"""Sends one mail merge email through a Gmail draft, and reconciles a draft after a crash.

Gmail replaces the Message-ID of every email it sends, including a sent draft's, but keeps
the draft's thread. So the draft and thread IDs, stored before the send, prove either way
whether the email went.
"""

import logging
from typing import Any
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationValidationError,
)
from models.integrations import IntegrationConnection
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import build_personal_oauth_access_token_resolver
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import MailMergeDelivery, MailMergeDraft, MailMergeMessage

from ..client import GmailClient
from .send_message import build_raw_message
from .utils import extract_headers

logger = logging.getLogger(__name__)


class GmailMergeSender:
    def __init__(self, client: GmailClient) -> None:
        self._client = client

    async def create_draft(self, message: MailMergeMessage) -> MailMergeDraft:
        raw = build_raw_message(
            to=[message.to], subject=message.subject, body_html=message.body_html
        )
        payload = await self._client.post(
            "users/me/drafts",
            operation="create_merge_draft",
            policy=IntegrationRequestPolicy.MUTATION,
            json={"message": {"raw": raw}},
        )
        draft_id = _identifier(payload.get("id") if isinstance(payload, dict) else None)
        draft_message = payload.get("message") if isinstance(payload, dict) else None
        thread_id = _identifier(
            draft_message.get("threadId") if isinstance(draft_message, dict) else None
        )
        if draft_id is None or thread_id is None:
            # An unsent draft without its IDs is never sent, so nothing reached the recipient.
            raise IntegrationValidationError(
                "Gmail didn't return the draft's IDs",
                provider_key="gmail",
                operation="create_merge_draft",
                failure_disposition=IntegrationFailureDisposition.REJECTED,
                error_code="invalid_draft_response",
            )
        return MailMergeDraft(draft_id=draft_id, thread_id=thread_id)

    async def send_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        payload = await self._client.post(
            "users/me/drafts/send",
            operation="send_merge_draft",
            policy=IntegrationRequestPolicy.MUTATION,
            json={"id": draft.draft_id},
        )
        message_id = _identifier(payload.get("id") if isinstance(payload, dict) else None)
        return await self._sent(message_id)

    async def check_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        try:
            await self._client.get(
                f"users/me/drafts/{quote(draft.draft_id, safe='')}",
                operation="check_merge_draft",
                policy=IntegrationRequestPolicy.READ,
                params={"format": "minimal"},
            )
            return MailMergeDelivery(state="unsent")
        except IntegrationNotFoundError:
            pass
        if draft.thread_id is None:
            return MailMergeDelivery(state="unknown")
        try:
            thread = await self._client.get(
                f"users/me/threads/{quote(draft.thread_id, safe='')}",
                operation="check_merge_draft",
                policy=IntegrationRequestPolicy.READ,
                params={"format": "minimal"},
            )
        except IntegrationNotFoundError:
            # The draft and its thread were deleted by hand, so nothing proves either way.
            return MailMergeDelivery(state="unknown")
        sent_id = _sent_message_id(thread)
        if sent_id is None:
            return MailMergeDelivery(state="unknown")
        return await self._sent(sent_id)

    async def _sent(self, message_id: str | None) -> MailMergeDelivery:
        """Returns a sent delivery with the sent copy's Message-ID, which bounces quote."""
        if message_id is None:
            return MailMergeDelivery(state="sent")
        try:
            payload = await self._client.get(
                f"users/me/messages/{quote(message_id, safe='')}",
                operation="read_merge_message_id",
                policy=IntegrationRequestPolicy.READ,
                params={"format": "metadata", "metadataHeaders": "Message-ID"},
            )
        except IntegrationError:
            # The email went; only the header for later bounce matching is missing.
            logger.warning("Couldn't read a sent merge email's Message-ID", exc_info=True)
            return MailMergeDelivery(state="sent", provider_message_id=message_id)
        header = extract_headers(payload).get("message-id", "")[:998] or None
        return MailMergeDelivery(
            state="sent", provider_message_id=message_id, message_id_header=header
        )


def open_merge_sender(db: AsyncSession, connection: IntegrationConnection) -> GmailMergeSender:
    """Returns a sender for the connection's mailbox, with Gmail's throttling errors mapped."""
    access_token = build_personal_oauth_access_token_resolver(
        db,
        connection,
        expected_provider_key="gmail",
        refresh_token=refresh_oauth_credential,
        credential_error=lambda: IntegrationAuthError(
            "The Gmail connection needs to be reconnected",
            provider_key="gmail",
            connection_id=str(connection.id),
            operation="open_merge_sender",
        ),
        open_transaction_error="Mail merge senders must close database transactions before I/O",
    )
    return GmailMergeSender(GmailClient(access_token, send_errors=True))


def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= 512 else None


def _sent_message_id(thread: Any) -> str | None:
    messages = thread.get("messages") if isinstance(thread, dict) else None
    for message in messages if isinstance(messages, list) else ():
        if isinstance(message, dict) and "SENT" in (message.get("labelIds") or ()):
            return _identifier(message.get("id"))
    return None
