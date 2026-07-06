# apps/api/services/jobs/utils.py

"""Utility helpers for generic background jobs."""

import hashlib
import json
import random

from sqlalchemy.exc import IntegrityError

from core.settings import settings

MAX_ERROR_MESSAGE_LENGTH = 1000
JOBS_IN_FLIGHT_UNIQUE_INDEX = "uq_jobs_in_flight"


def compute_content_hash(payload: dict[str, object] | None) -> str:
    """Return a stable sha256 hash for a JSON payload."""
    encoded = json.dumps(
        payload or {},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def retry_backoff(attempts: int) -> float:
    """Return capped exponential retry backoff with +/-20% jitter."""
    exponent = max(attempts - 1, 0)
    base_delay = settings.JOBS_RETRY_BACKOFF_BASE_SECONDS * (2**exponent)
    capped_delay = min(base_delay, settings.JOBS_RETRY_BACKOFF_CAP_SECONDS)
    jitter_multiplier = random.uniform(0.8, 1.2)  # noqa: S311 - not security-sensitive
    return capped_delay * jitter_multiplier


def sanitize_error_message(message: str | None) -> str | None:
    """Persist concise operational error text without oversized payload dumps."""
    if message is None:
        return None
    normalized = " ".join(message.split())
    if not normalized:
        return None
    return normalized[:MAX_ERROR_MESSAGE_LENGTH]


def is_jobs_in_flight_integrity_error(exc: IntegrityError) -> bool:
    """Return whether an integrity error came from the in-flight dedup index."""
    constraint_names = _integrity_constraint_names(exc)
    return (
        JOBS_IN_FLIGHT_UNIQUE_INDEX in constraint_names
        or JOBS_IN_FLIGHT_UNIQUE_INDEX in str(exc)
    )


def _integrity_constraint_names(exc: IntegrityError) -> set[str]:
    names: set[str] = set()
    seen: set[int] = set()
    pending: list[object | None] = [exc, getattr(exc, "orig", None)]

    while pending:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))

        for attr_name in ("constraint_name", "constraint"):
            attr = getattr(item, attr_name, None)
            if isinstance(attr, str) and attr:
                names.add(attr)

        diag = getattr(item, "diag", None)
        if diag is not None:
            constraint_name = getattr(diag, "constraint_name", None)
            if isinstance(constraint_name, str) and constraint_name:
                names.add(constraint_name)

        pending.extend(
            (
                getattr(item, "orig", None),
                getattr(item, "__cause__", None),
                getattr(item, "__context__", None),
            )
        )

    return names
