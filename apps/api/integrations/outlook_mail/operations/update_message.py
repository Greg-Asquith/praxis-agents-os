# apps/api/integrations/outlook_mail/operations/update_message.py

"""Updates the read and flag state of one Outlook message."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import MailWriteState, message_path


async def update_message(
    client: MicrosoftGraphClient,
    *,
    state: MailWriteState,
    message_id: str,
    is_read: bool | None,
    flagged: bool | None,
) -> None:
    changes = {}
    if is_read is not None:
        changes["isRead"] = is_read
    if flagged is not None:
        changes["flag"] = {"flagStatus": "flagged" if flagged else "notFlagged"}
    state.step = "update"
    payload = await client.patch(
        message_path(message_id),
        operation="update_message",
        policy=IntegrationRequestPolicy.MUTATION,
        json=changes,
    )
    state.created(payload)
