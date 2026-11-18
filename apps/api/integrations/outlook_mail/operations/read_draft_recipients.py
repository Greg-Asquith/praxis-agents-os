# apps/api/integrations/outlook_mail/operations/read_draft_recipients.py

"""Reads every address a draft will send to, for the Do Not Email check before sending."""

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from .utils import message_path

_RECIPIENT_FIELDS = ("toRecipients", "ccRecipients", "bccRecipients")


async def read_draft_recipients(client, *, message_id: str, operation: str) -> list[str]:
    payload = await client.get(
        message_path(message_id),
        operation=operation,
        policy=IntegrationRequestPolicy.READ,
        params={"$select": ",".join(_RECIPIENT_FIELDS)},
    )
    addresses: list[str] = []
    for field in _RECIPIENT_FIELDS:
        values = payload.get(field) if isinstance(payload, dict) else None
        if not isinstance(values, list):
            raise _unreadable(operation)
        for value in values:
            email = value.get("emailAddress") if isinstance(value, dict) else None
            address = email.get("address") if isinstance(email, dict) else None
            if not isinstance(address, str) or not address.strip():
                raise _unreadable(operation)
            addresses.append(address)
    return addresses


def _unreadable(operation: str) -> IntegrationValidationError:
    # Unchecked recipients would bypass the Do Not Email list, so the send stops here.
    return IntegrationValidationError(
        "Outlook did not return the draft's recipients. Check the draft in Outlook.",
        provider_key="outlook_mail",
        operation=operation,
        failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        error_code="draft_recipients_unavailable",
    )
