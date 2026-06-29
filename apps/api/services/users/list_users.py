# apps/api/services/users/list_users.py

"""List users for super-admin user management."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.users.schemas import UserRead, UsersListResponse


async def list_users(
    db: AsyncSession,
    *,
    q: str | None,
    include_deleted: bool,
    limit: int,
    offset: int,
) -> UsersListResponse:
    stmt = select(User)
    if not include_deleted:
        stmt = stmt.where(User.deleted.is_(False))
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset))
    return UsersListResponse(
        users=[UserRead.from_user(user) for user in result.scalars().all()],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
