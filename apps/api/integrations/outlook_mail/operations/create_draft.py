# apps/api/integrations/outlook_mail/operations/create_draft.py

"""Creates a new Outlook draft without sending it."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import MailWriteState, graph_recipients


async def create_draft(
    client: MicrosoftGraphClient,
    *,
    state: MailWriteState,
    to: list[str],
    subject: str,
    body_html: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> None:
    state.step = "draft"
    payload = await client.post(
        "/me/messages",
        operation="create_draft",
        policy=IntegrationRequestPolicy.MUTATION,
        json={
            "subject": subject,
            "body": {"contentType": "html", "content": body_html},
            "toRecipients": graph_recipients(to),
            "ccRecipients": graph_recipients(cc or []),
            "bccRecipients": graph_recipients(bcc or []),
        },
    )
    state.created(payload)
