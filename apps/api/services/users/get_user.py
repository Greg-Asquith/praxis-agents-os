# apps/api/services/users/get_user.py

"""Fetch one user for super-admin user management."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from services.users.schemas import UserRead
from services.users.utils import get_user_or_raise


async def get_user(
    db: AsyncSession,
    *,
    user_id: UUID,
    include_deleted: bool = False,
) -> UserRead:
    user = await get_user_or_raise(db, user_id=user_id, include_deleted=include_deleted)
    return UserRead.from_user(user)
