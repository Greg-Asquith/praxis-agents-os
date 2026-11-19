# apps/api/services/mail_merge/schemas.py

"""Pydantic contracts for the mail merge progress routes."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

# What the operator sees for a row. "waiting" covers queued and in-flight rows while the
# merge runs, and rows left unsent once it ends.
type MailMergeRowState = Literal["waiting", "sent", "failed", "unverified", "skipped"]


class MailMergeCounts(BaseModel):
    total: int
    waiting: int
    sent: int
    failed: int
    unverified: int
    skipped: int


class MailMergeRecipientRead(BaseModel):
    position: int
    email: str
    state: MailMergeRowState
    # Why a row failed or was skipped, such as do_not_email or rate_limited.
    reason: str | None
    sent_at: datetime | None


class MailMergeRead(BaseModel):
    id: UUID
    provider_key: str
    sender_address: str
    status: str
    stop_reason: str | None
    created_at: datetime
    finished_at: datetime | None
    # While sending: when the last email should go. While paused for the daily limit: when
    # the mailbox has room again.
    estimated_finish: datetime | None
    resumes_at: datetime | None
    counts: MailMergeCounts
    recipients: list[MailMergeRecipientRead]
