# apps/api/services/email_suppressions/check_recipients.py

"""The Do Not Email check that every email send path calls."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.email_suppression import WorkspaceEmailSuppression
from services.email_suppressions.utils import address_match_key
from utils.validation import normalize_email


async def find_suppressed_recipients(
    db: AsyncSession, *, workspace_id: UUID, addresses: Iterable[str]
) -> list[str]:
    """Returns the given addresses that reach someone on the workspace's list, in order.

    Each is returned as given, trimmed and lower-cased. Never returns a reason, so a caller
    can't pass one to an agent.
    """
    keys = {normalize_email(value): address_match_key(value) for value in addresses}
    if not keys:
        return []
    listed = set(
        await db.scalars(
            select(WorkspaceEmailSuppression.match_key).where(
                WorkspaceEmailSuppression.workspace_id == workspace_id,
                WorkspaceEmailSuppression.match_key.in_(set(keys.values())),
            )
        )
    )
    return [address for address, key in keys.items() if key in listed]
