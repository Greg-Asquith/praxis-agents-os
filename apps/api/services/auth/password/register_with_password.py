# apps/api/services/auth/register_with_password.py

"""Register a user with email/password auth."""

from fastapi import Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError
from core.settings import settings
from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.auth.schemas import AuthResponse, RegisterRequest
from services.auth.utils import (
    get_user_by_email,
    issue_auth_response,
    record_auth_security_event,
)
from services.security import SecurityEventType
from services.workspaces.provisioning import provision_personal_workspace
from utils.validation import normalize_email, validate_email, validate_password_strength


async def register_with_password(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    payload: RegisterRequest,
) -> AuthResponse:
    if not settings.ALLOW_SIGNUP:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_REGISTER_FAILED,
            request=request,
            user_email=payload.email,
            details={"reason": "signup_disabled"},
            committed=True,
        )
        raise AuthorizationError("Signup is disabled")
    if not settings.EMAIL_AUTH_ENABLED:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_REGISTER_FAILED,
            request=request,
            user_email=payload.email,
            details={"reason": "email_auth_disabled"},
            committed=True,
        )
        raise AuthorizationError("Email authentication is disabled")

    email = normalize_email(payload.email)
    validate_email(email)
    validate_password_strength(payload.password)

    existing = await get_user_by_email(db, email, include_deleted=True)
    if existing:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_REGISTER_FAILED,
            request=request,
            user_email=email,
            details={"reason": "email_exists", "deleted": existing.deleted},
            committed=True,
        )
        raise ConflictError("A user with that email already exists", conflicting_resource="user")

    user = User(email=email, display_name=payload.display_name, is_active=True)
    user.set_password(payload.password)
    db.add(user)

    try:
        await db.flush()
    except IntegrityError as exc:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_REGISTER_FAILED,
            request=request,
            user_email=email,
            details={"reason": "email_exists"},
            committed=True,
        )
        raise ConflictError(
            "A user with that email already exists", conflicting_resource="user"
        ) from exc

    workspace = await provision_personal_workspace(db, user)
    await record_user_audit_event(
        db,
        action=AuditAction.CREATE,
        user=user,
        actor=user,
        workspace_id=workspace.id,
        details={"source": "email_registration"},
        request=request,
    )

    return await issue_auth_response(
        db,
        request=request,
        response=response,
        user=user,
        event_type=SecurityEventType.AUTH_REGISTER_SUCCEEDED,
        details={"method": "password"},
    )
