# apps/api/services/mail_merge/budget.py

"""How many more merge emails a mailbox can send in the rolling 24 hours."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.mail_merge import MailMerge, MailMergeRecipient, MailMergeTestSend

# Providers count their daily limits over a rolling 24 hours, not a calendar day.
BUDGET_WINDOW = timedelta(hours=24)
# Entra issues every Microsoft personal account token from this tenant.
MICROSOFT_CONSUMER_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"

_GMAIL_PERSONAL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


class MailAccountKind(StrEnum):
    GMAIL_PERSONAL = "gmail_personal"
    GOOGLE_WORKSPACE = "google_workspace"
    OUTLOOK_PERSONAL = "outlook_personal"
    MICROSOFT_365 = "microsoft_365"


@dataclass(frozen=True)
class SendBudget:
    cap: int
    used: int
    # When the next send fits again; None while there is room.
    frees_at: datetime | None

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)


def mail_account_kind(
    *, provider_key: str, sender_address: str, tenant_id: str | None
) -> MailAccountKind:
    """Returns the kind of mailbox, which sets its provider limit.

    An Outlook connection with no recorded tenant counts as personal, the lower cap.
    """
    if provider_key == "gmail":
        domain = sender_address.rpartition("@")[2].strip().lower()
        if domain in _GMAIL_PERSONAL_DOMAINS:
            return MailAccountKind.GMAIL_PERSONAL
        return MailAccountKind.GOOGLE_WORKSPACE
    if tenant_id is None or tenant_id.lower() == MICROSOFT_CONSUMER_TENANT_ID:
        return MailAccountKind.OUTLOOK_PERSONAL
    return MailAccountKind.MICROSOFT_365


def daily_send_cap(kind: MailAccountKind) -> int:
    """Returns the most merge and test emails the mailbox may send in 24 hours."""
    return {
        MailAccountKind.GMAIL_PERSONAL: settings.MAIL_MERGE_DAILY_CAP_GMAIL_PERSONAL,
        MailAccountKind.GOOGLE_WORKSPACE: settings.MAIL_MERGE_DAILY_CAP_GOOGLE_WORKSPACE,
        MailAccountKind.OUTLOOK_PERSONAL: settings.MAIL_MERGE_DAILY_CAP_OUTLOOK_PERSONAL,
        MailAccountKind.MICROSOFT_365: settings.MAIL_MERGE_DAILY_CAP_MICROSOFT_365,
    }[kind]


async def get_send_budget(
    db: AsyncSession, *, connection_id: UUID, kind: MailAccountKind, now: datetime
) -> SendBudget:
    """Gets the mailbox's budget from merge and test emails attempted in the last 24 hours.

    Every attempt counts, whether or not it was confirmed, because a provider counts an
    accepted message even when Praxis never learns that it was sent.
    """
    cap = daily_send_cap(kind)
    since = now - BUDGET_WINDOW
    attempted = union_all(
        select(MailMergeRecipient.attempted_at.label("attempted_at"))
        .join(MailMerge, MailMerge.id == MailMergeRecipient.merge_id)
        .where(
            MailMerge.connection_id == connection_id,
            MailMergeRecipient.attempted_at > since,
        ),
        select(MailMergeTestSend.attempted_at.label("attempted_at")).where(
            MailMergeTestSend.connection_id == connection_id,
            MailMergeTestSend.attempted_at > since,
        ),
    ).subquery()
    used = await db.scalar(select(func.count()).select_from(attempted)) or 0
    frees_at = None
    if used >= cap:
        # The send that must leave the window before one more fits under the cap.
        oldest = await db.scalar(
            select(attempted.c.attempted_at)
            .order_by(attempted.c.attempted_at)
            .offset(used - cap)
            .limit(1)
        )
        frees_at = oldest + BUDGET_WINDOW if oldest is not None else None
    return SendBudget(cap=cap, used=used, frees_at=frees_at)


def estimate_merge_finish(*, count: int, budget: SendBudget, now: datetime) -> datetime:
    """Returns roughly when a merge of count emails finishes, across days when it must."""
    interval = timedelta(seconds=settings.MAIL_MERGE_SEND_INTERVAL_SECONDS)
    if count <= budget.remaining:
        return now + interval * count
    waiting = count - budget.remaining
    days = math.ceil(waiting / budget.cap)
    return now + BUDGET_WINDOW * days + interval * (waiting - (days - 1) * budget.cap)
