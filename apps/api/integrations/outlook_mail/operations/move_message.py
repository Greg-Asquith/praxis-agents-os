# apps/api/integrations/outlook_mail/operations/move_message.py

"""Moves one Outlook message to a previously resolved folder."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import MailWriteState, message_path


async def move_message(
    client: MicrosoftGraphClient,
    *,
    state: MailWriteState,
    message_id: str,
    destination_id: str,
) -> None:
    state.step = "move"
    payload = await client.post(
        f"{message_path(message_id)}/move",
        operation="move_message",
        policy=IntegrationRequestPolicy.MUTATION,
        json={"destinationId": destination_id},
    )
    state.created(payload)
