# apps/api/services/agent_runs/domain.py

"""Status vocabulary and transition rules for generic agent runs.

This is the execution-side lifecycle. It is intentionally narrower than the scheduler's
claim vocabulary in services/agent_schedules/runs.py: an agent run is either pending,
running, suspended for approval, or in a terminal state. Retry/claim bookkeeping stays
on agent_schedule_runs.
"""

from dataclasses import dataclass

RUN_STATUS_PENDING = "pending"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_AWAITING_APPROVAL = "awaiting_approval"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELLED = "cancelled"

ALL_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_PENDING,
        RUN_STATUS_RUNNING,
        RUN_STATUS_AWAITING_APPROVAL,
        RUN_STATUS_COMPLETED,
        RUN_STATUS_FAILED,
        RUN_STATUS_CANCELLED,
    }
)

TERMINAL_RUN_STATUSES = frozenset({RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED})

# Allowed forward transitions. A terminal status has no outgoing edges.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    RUN_STATUS_PENDING: frozenset({RUN_STATUS_RUNNING, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED}),
    RUN_STATUS_RUNNING: frozenset(
        {
            RUN_STATUS_AWAITING_APPROVAL,
            RUN_STATUS_COMPLETED,
            RUN_STATUS_FAILED,
            RUN_STATUS_CANCELLED,
        }
    ),
    RUN_STATUS_AWAITING_APPROVAL: frozenset(
        {RUN_STATUS_RUNNING, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED}
    ),
    RUN_STATUS_COMPLETED: frozenset(),
    RUN_STATUS_FAILED: frozenset(),
    RUN_STATUS_CANCELLED: frozenset(),
}

RUN_TRIGGER_INTERACTIVE = "interactive"
RUN_TRIGGER_SCHEDULED = "scheduled"
RUN_TRIGGER_DELEGATED = "delegated"

ALL_RUN_TRIGGERS = frozenset(
    {RUN_TRIGGER_INTERACTIVE, RUN_TRIGGER_SCHEDULED, RUN_TRIGGER_DELEGATED}
)


def can_transition(current: str, target: str) -> bool:
    """Return whether moving a run from current to target status is allowed."""
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def is_terminal(status: str) -> bool:
    """Return whether a run status is terminal (no further transitions)."""
    return status in TERMINAL_RUN_STATUSES


@dataclass(frozen=True)
class RunUsageSnapshot:
    """A point-in-time usage record mirroring pydantic-ai RunUsage.

    Hot fields are persisted as columns for billing/audit queries; pass the full
    serialized RunUsage as raw_json to preserve provider details on agent_runs.usage_json.
    """

    input_tokens: int | None = None
    input_tokens_cached: int | None = None
    output_tokens: int | None = None
    requests: int | None = None
    tool_calls: int | None = None
    raw_json: dict | None = None
