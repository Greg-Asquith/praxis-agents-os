# apps/api/tests/factories/users.py
"""User model factories for tests."""

from uuid import UUID, uuid4

from models.user import User


def build_user(
    *,
    user_id: UUID | None = None,
    email: str = "user@example.com",
    display_name: str | None = "Test User",
    password: str | None = None,
    is_active: bool = True,
) -> User:
    """Build an unsaved user model for service tests."""
    user = User(
        id=user_id or uuid4(),
        email=email,
        display_name=display_name,
        is_active=is_active,
    )
    if password is not None:
        user.set_password(password)
    return user
