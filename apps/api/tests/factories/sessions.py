# apps/api/tests/factories/sessions.py
"""Session model factories for tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from models.session import Session


def build_session(
    *,
    session_id: UUID | None = None,
    user_id: UUID | None = None,
    token_hash: str | None = None,
    expires_at: datetime | None = None,
    twofa_verified: bool = True,
) -> Session:
    """Build an unsaved session model for service tests."""
    return Session(
        id=session_id or uuid4(),
        user_id=user_id or uuid4(),
        token_hash=token_hash or f"test-token-hash-{uuid4()}",
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        twofa_verified=twofa_verified,
    )
