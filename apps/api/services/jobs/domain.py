# apps/api/services/jobs/domain.py

"""Domain constants for generic background jobs."""

import re

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_CANCELLED = "cancelled"

IN_FLIGHT_JOB_STATUSES = frozenset({JOB_STATUS_PENDING, JOB_STATUS_RUNNING})
TERMINAL_JOB_STATUSES = frozenset(
    {JOB_STATUS_SUCCEEDED, JOB_STATUS_FAILED, JOB_STATUS_CANCELLED}
)

JOB_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_.]*$")


def is_valid_job_kind(kind: str) -> bool:
    """Return whether a job kind follows the dotted namespace rule."""
    return bool(JOB_KIND_PATTERN.fullmatch(kind))
