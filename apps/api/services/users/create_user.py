# apps/api/services/users/create_user.py

"""Create a user through super-admin user management."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.users.schemas import UserCreateRequest, UserRead
from services.workspaces.provisioning import provision_personal_workspace
from utils.validation import normalize_email, validate_email, validate_password_strength


async def create_user(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    payload: UserCreateRequest,
) -> UserRead:
    email = normalize_email(payload.email)
    validate_email(email)
    if payload.password:
        validate_password_strength(payload.password)

    user = User(
        email=email,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
        is_active=payload.is_active,
    )
    if payload.password:
        user.set_password(payload.password)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "A user with that email already exists", conflicting_resource="user"
        ) from exc

    workspace = await provision_personal_workspace(db, user)
    await record_user_audit_event(
        db,
        action=AuditAction.CREATE,
        user=user,
        actor=actor,
        request=request,
        workspace_id=workspace.id,
        details={"source": "admin", "is_active": payload.is_active},
    )
    return UserRead.from_user(user)
