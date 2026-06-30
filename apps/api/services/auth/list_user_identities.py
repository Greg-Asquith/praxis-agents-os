# apps/api/services/auth/list_user_identities.py

"""List the authenticated user's connected sign-in methods."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User, UserAuth
from services.auth.schemas import ConnectedIdentity, IdentitiesResponse


async def list_user_identities(db: AsyncSession, *, user: User) -> IdentitiesResponse:
    result = await db.execute(
        select(UserAuth)
        .where(UserAuth.user_id == user.id, UserAuth.deleted.is_(False))
        .order_by(UserAuth.created_at)
    )
    identities = [
        ConnectedIdentity(
            provider=record.provider,
            email=record.email,
            email_verified=record.email_verified,
            created_at=record.created_at,
        )
        for record in result.scalars().all()
    ]
    return IdentitiesResponse(has_password=user.has_password, identities=identities)
