# apps/api/services/users/list_users.py

"""List users for super-admin user management."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.users.schemas import UserRead, UsersListResponse
from utils.pagination import paginate


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

    users, total = await paginate(db, stmt, User.created_at.desc(), limit=limit, offset=offset)
    return UsersListResponse(
        users=[UserRead.from_user(user) for user in users],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
