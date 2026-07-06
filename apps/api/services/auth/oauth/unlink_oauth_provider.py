# apps/api/services/auth/oauth/unlink_oauth_provider.py

"""Unlink an OAuth provider from the current user."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.user import User, UserAuth
from services.audit_events import AuditAction, AuditResourceType, record_user_audit_event
from services.auth.list_user_identities import list_user_identities
from services.auth.schemas import IdentitiesResponse


async def unlink_oauth_provider(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    provider_name: str,
) -> IdentitiesResponse:
    provider_name = provider_name.strip().lower()

    result = await db.execute(
        select(UserAuth).where(
            UserAuth.user_id == user.id,
            UserAuth.deleted.is_(False),
        )
    )
    records = list(result.scalars().all())
    to_remove = [record for record in records if record.provider == provider_name]
    if not to_remove:
        raise NotFoundError("No linked account for this provider", resource_type="user_auth")

    remaining_oauth = sum(1 for record in records if record.provider != provider_name)
    remaining_methods = remaining_oauth + (1 if user.has_password else 0)
    if remaining_methods < 1:
        raise ConflictError(
            "You can't remove your only sign-in method", conflicting_resource="user_auth"
        )

    for record in to_remove:
        record.soft_delete()

    await db.flush()
    await record_user_audit_event(
        db,
        action=AuditAction.DELETE,
        user=user,
        actor=user,
        resource_type=AuditResourceType.USER_AUTH,
        details={"provider": provider_name, "intent": "unlink"},
        request=request,
    )
    return await list_user_identities(db, user=user)
