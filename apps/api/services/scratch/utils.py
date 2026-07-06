# apps/api/services/scratch/utils.py

"""Helpers specific to agent scratch services."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.sql.elements import ColumnElement

from core.settings import settings
from models.scratch import ScratchEntry
from services.scratch.domain import ScratchScope


def scratch_expires_at(*, now: datetime | None = None) -> datetime:
    """Return the rolling expiry timestamp for a scratch entry."""
    return (now or datetime.now(UTC)) + timedelta(days=settings.SCRATCH_TTL_DAYS)


def scope_filters(scope: ScratchScope) -> list[ColumnElement[bool]]:
    """Return SQLAlchemy filters for the supplied scratch scope."""
    if scope.conversation_id is not None:
        return [ScratchEntry.conversation_id == scope.conversation_id]
    if scope.run_id is not None:
        return [ScratchEntry.run_id == scope.run_id]
    raise AssertionError("ScratchScope enforces exactly one owner")


def scope_values(scope: ScratchScope) -> dict[str, object]:
    """Return insert values for the supplied scope."""
    return {
        "conversation_id": scope.conversation_id,
        "run_id": scope.run_id,
    }
