# apps/api/services/users/utils.py

"""Service-specific helpers for user-management operations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.user import User


async def get_user_or_raise(
    db: AsyncSession,
    *,
    user_id: UUID,
    include_deleted: bool = False,
) -> User:
    stmt = select(User).where(User.id == user_id)
    if not include_deleted:
        stmt = stmt.where(User.deleted.is_(False))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found", resource_type="user", resource_id=str(user_id))
    return user
