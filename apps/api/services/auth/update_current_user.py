# apps/api/services/auth/update_current_user.py

"""Update the authenticated user's profile."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, record_user_audit_event
from services.auth.schemas import AuthUser, CurrentUserUpdateRequest
from services.auth.utils import build_auth_user


async def update_current_user(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    payload: CurrentUserUpdateRequest,
) -> AuthUser:
    changed_fields: list[str] = []
    if "display_name" in payload.model_fields_set and payload.display_name != user.display_name:
        user.display_name = payload.display_name
        changed_fields.append("display_name")

    if "default_workspace_id" in payload.model_fields_set:
        if payload.default_workspace_id is None:
            raise AppValidationError(
                "Default workspace cannot be cleared",
                field="default_workspace_id",
            )

        membership = await db.scalar(
            select(WorkspaceMembership)
            .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
            .where(
                WorkspaceMembership.user_id == user.id,
                WorkspaceMembership.workspace_id == payload.default_workspace_id,
                WorkspaceMembership.deleted.is_(False),
                Workspace.deleted.is_(False),
            )
        )
        if membership is None:
            raise AppValidationError(
                "Workspace not found or access denied",
                field="default_workspace_id",
            )

        if user.default_workspace_id != payload.default_workspace_id:
            user.default_workspace_id = payload.default_workspace_id
            changed_fields.append("default_workspace_id")

    if changed_fields:
        await db.flush()
        await record_user_audit_event(
            db,
            action=AuditAction.UPDATE,
            user=user,
            actor=user,
            details={"fields": changed_fields},
            request=request,
        )
    return await build_auth_user(db, user)
