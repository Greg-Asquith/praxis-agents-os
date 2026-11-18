# apps/api/services/mail_merge/utils.py

"""Guarded status moves for merges and their recipients."""

from datetime import datetime

from core.exceptions.general import ConflictError
from models.mail_merge import MailMerge, MailMergeRecipient
from services.mail_merge.domain import (
    FINAL_MERGE_STATUSES,
    can_transition_merge,
    can_transition_recipient,
)


def move_merge(
    merge: MailMerge, target: str, *, now: datetime, stop_reason: str | None = None
) -> None:
    """Moves a merge the caller has locked to target, or raises ConflictError."""
    if not can_transition_merge(merge.status, target):
        raise ConflictError(
            f"Cannot move mail merge from {merge.status!r} to {target!r}",
            conflicting_resource="mail_merge",
            details={"mail_merge_id": str(merge.id), "from": merge.status, "to": target},
        )
    merge.status = target
    merge.stop_reason = stop_reason
    if target in FINAL_MERGE_STATUSES:
        merge.finished_at = now


def move_recipient(row: MailMergeRecipient, target: str) -> None:
    """Moves a recipient row the caller has locked to target, or raises ConflictError."""
    if not can_transition_recipient(row.status, target):
        raise ConflictError(
            f"Cannot move mail merge recipient from {row.status!r} to {target!r}",
            conflicting_resource="mail_merge_recipient",
            details={"recipient_id": str(row.id), "from": row.status, "to": target},
        )
    row.status = target
