# apps/api/services/mail_merge/domain.py

"""The mail merge and recipient lifecycles."""

MERGE_STATUS_QUEUED = "queued"
MERGE_STATUS_SENDING = "sending"
MERGE_STATUS_PAUSED = "paused"
MERGE_STATUS_COMPLETED = "completed"
MERGE_STATUS_CANCELLED = "cancelled"
MERGE_STATUS_STOPPED = "stopped"

FINAL_MERGE_STATUSES = frozenset(
    {MERGE_STATUS_COMPLETED, MERGE_STATUS_CANCELLED, MERGE_STATUS_STOPPED}
)

# A paused merge resumes through queued, so the active-mailbox index is checked again.
ALLOWED_MERGE_TRANSITIONS: dict[str, frozenset[str]] = {
    MERGE_STATUS_QUEUED: frozenset(
        {MERGE_STATUS_SENDING, MERGE_STATUS_PAUSED, MERGE_STATUS_CANCELLED, MERGE_STATUS_STOPPED}
    ),
    MERGE_STATUS_SENDING: frozenset(
        {
            MERGE_STATUS_PAUSED,
            MERGE_STATUS_COMPLETED,
            MERGE_STATUS_CANCELLED,
            MERGE_STATUS_STOPPED,
        }
    ),
    MERGE_STATUS_PAUSED: frozenset(
        {MERGE_STATUS_QUEUED, MERGE_STATUS_CANCELLED, MERGE_STATUS_STOPPED}
    ),
    MERGE_STATUS_COMPLETED: frozenset(),
    MERGE_STATUS_CANCELLED: frozenset(),
    MERGE_STATUS_STOPPED: frozenset(),
}

RECIPIENT_STATUS_PENDING = "pending"
RECIPIENT_STATUS_SENDING = "sending"
RECIPIENT_STATUS_SENT = "sent"
RECIPIENT_STATUS_FAILED = "failed"
RECIPIENT_STATUS_UNVERIFIED = "unverified"
RECIPIENT_STATUS_SKIPPED = "skipped"

# A sending row returns to pending only when the provider rejected the send; one whose
# outcome is unknown becomes unverified and is never sent again automatically.
ALLOWED_RECIPIENT_TRANSITIONS: dict[str, frozenset[str]] = {
    RECIPIENT_STATUS_PENDING: frozenset({RECIPIENT_STATUS_SENDING, RECIPIENT_STATUS_SKIPPED}),
    RECIPIENT_STATUS_SENDING: frozenset(
        {
            RECIPIENT_STATUS_PENDING,
            RECIPIENT_STATUS_SENT,
            RECIPIENT_STATUS_FAILED,
            RECIPIENT_STATUS_UNVERIFIED,
        }
    ),
    RECIPIENT_STATUS_SENT: frozenset(),
    RECIPIENT_STATUS_FAILED: frozenset(),
    RECIPIENT_STATUS_UNVERIFIED: frozenset(),
    RECIPIENT_STATUS_SKIPPED: frozenset(),
}


def can_transition_merge(current: str, target: str) -> bool:
    """Checks whether a merge may move from current to target status."""
    return target in ALLOWED_MERGE_TRANSITIONS.get(current, frozenset())


def can_transition_recipient(current: str, target: str) -> bool:
    """Checks whether a recipient row may move from current to target status."""
    return target in ALLOWED_RECIPIENT_TRANSITIONS.get(current, frozenset())
