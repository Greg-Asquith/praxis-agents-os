# apps/api/services/email_suppressions/refuse_suppressed_recipients.py

"""Refuse a whole single send when any recipient is on the Do Not Email list."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationFailureDisposition, IntegrationValidationError
from services.email_suppressions.check_recipients import find_suppressed_recipients

SUPPRESSED_RECIPIENT_ERROR_CODE = "do_not_email"


async def refuse_suppressed_recipients(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    addresses: Iterable[str],
    provider_key: str,
    operation: str,
) -> None:
    """Raises before the provider send so nobody, listed or not, receives a partial send.

    Raises:
        IntegrationValidationError: Thrown when any address is listed. The message names
            the addresses and never the reason.
    """
    listed = await find_suppressed_recipients(db, workspace_id=workspace_id, addresses=addresses)
    if not listed:
        return
    names = listed[0] if len(listed) == 1 else f"{', '.join(listed[:-1])} and {listed[-1]}"
    verb = "is" if len(listed) == 1 else "are"
    raise IntegrationValidationError(
        f"{names} {verb} on this workspace's Do Not Email list, so nothing was sent. "
        "Remove them to send to everyone else.",
        provider_key=provider_key,
        operation=operation,
        failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        error_code=SUPPRESSED_RECIPIENT_ERROR_CODE,
    )
