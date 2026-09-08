# apps/api/integrations/outlook_mail/operations/send_message.py

"""Sends an existing draft using its immutable message reference."""

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import MicrosoftGraphClient

from .utils import MailWriteState, message_path


async def send_message(client: MicrosoftGraphClient, *, state: MailWriteState) -> None:
    if state.message_id is None:
        raise ValueError("Sending requires a draft reference.")
    state.step = "send"
    await client.post(
        f"{message_path(state.message_id)}/send",
        operation="send_message",
        policy=IntegrationRequestPolicy.MUTATION,
    )
    state.applied_steps.append(state.step)
