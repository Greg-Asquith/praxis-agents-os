# apps/api/services/email_suppressions/flag_suppressed_recipients.py

"""Mark listed recipients on a send's approval display, so the card can block approval."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from services.email_suppressions.check_recipients import find_suppressed_recipients

SUPPRESSED_RECIPIENTS_DISPLAY_KEY = "_do_not_email"


async def flag_suppressed_recipients(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    display_args: dict[str, Any],
    addresses: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Returns the display args with any listed recipients under `_do_not_email`.

    Args:
        addresses: The recipients to check. Default: the `to`, `cc`, and `bcc` arguments.
    """
    if addresses is None:
        addresses = [
            value
            for key in ("to", "cc", "bcc")
            for value in display_args.get(key) or ()
            if isinstance(value, str)
        ]
    listed = await find_suppressed_recipients(db, workspace_id=workspace_id, addresses=addresses)
    if not listed:
        return display_args
    return {**display_args, SUPPRESSED_RECIPIENTS_DISPLAY_KEY: listed}
