# apps/api/integrations/outlook_mail/operations/send_merge_message.py

"""Sends one mail merge email through an Outlook draft, and reconciles a draft after a crash.

The Graph client asks for immutable IDs, so the draft's ID follows the email into Sent Items.
Reading that one ID proves whether it was sent: `isDraft` turns false on send.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationNotFoundError
from models.integrations import IntegrationConnection
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient, graph_client_for_connection
from services.integrations.plugin import MailMergeDelivery, MailMergeDraft, MailMergeMessage

from .create_draft import create_draft
from .send_message import send_message
from .utils import MailWriteState, message_path, object_payload


class OutlookMergeSender:
    def __init__(self, client: MicrosoftGraphClient) -> None:
        self._client = client

    async def create_draft(self, message: MailMergeMessage) -> MailMergeDraft:
        state = MailWriteState()
        await create_draft(
            self._client,
            state=state,
            to=[message.to],
            subject=message.subject,
            body_html=message.body_html,
        )
        # create_draft raises unless Outlook returned the draft's ID.
        return MailMergeDraft(
            draft_id=state.message_id or "", message_id_header=state.internet_message_id
        )

    async def send_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        await send_message(self._client, state=MailWriteState(message_id=draft.draft_id))
        return _sent(draft)

    async def check_draft(self, draft: MailMergeDraft) -> MailMergeDelivery:
        try:
            payload = object_payload(
                await self._client.get(
                    message_path(draft.draft_id),
                    operation="check_merge_draft",
                    policy=IntegrationRequestPolicy.READ,
                    params={"$select": "id,isDraft"},
                ),
                operation="check_merge_draft",
            )
        except IntegrationNotFoundError:
            # Deleted by hand, from Drafts or from Sent Items, so nothing proves either way.
            return MailMergeDelivery(state="unknown")
        if payload.get("isDraft") is True:
            return MailMergeDelivery(state="unsent")
        if payload.get("isDraft") is False:
            return _sent(draft)
        return MailMergeDelivery(state="unknown")


def open_merge_sender(db: AsyncSession, connection: IntegrationConnection) -> OutlookMergeSender:
    """Returns a sender for the connection's mailbox, with Graph throttling mapped."""
    return OutlookMergeSender(
        graph_client_for_connection(
            db, connection, expected_provider_key="outlook_mail", send_errors=True
        )
    )


def _sent(draft: MailMergeDraft) -> MailMergeDelivery:
    return MailMergeDelivery(
        state="sent",
        provider_message_id=draft.draft_id,
        message_id_header=draft.message_id_header,
    )
