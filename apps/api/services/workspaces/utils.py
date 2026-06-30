# apps/api/services/workspaces/utils.py

"""Service-specific helpers for workspace operations."""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.security import (
    SecurityEventType,
    safe_record_security_event,
    safe_record_security_event_committed,
)
from utils.request import request_ip

MANAGER_ROLES = {WorkspaceRole.OWNER.value, WorkspaceRole.ADMIN.value}
EDITOR_ROLES = {
    WorkspaceRole.OWNER.value,
    WorkspaceRole.ADMIN.value,
    WorkspaceRole.MEMBER.value,
}
READ_ROLES = {
    *EDITOR_ROLES,
    WorkspaceRole.READ_ONLY.value,
}


async def get_workspace_or_raise(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    include_deleted: bool = False,
    load_children: bool = False,
) -> Workspace:
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    if not include_deleted:
        stmt = stmt.where(Workspace.deleted.is_(False))
    if load_children:
        stmt = stmt.options(
            selectinload(Workspace.memberships),
            selectinload(Workspace.invitations),
        )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise NotFoundError(
            "Workspace not found",
            resource_type="workspace",
            resource_id=str(workspace_id),
        )
    return workspace


async def get_active_membership(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    load_workspace: bool = False,
) -> WorkspaceMembership | None:
    stmt = select(WorkspaceMembership).where(
        WorkspaceMembership.workspace_id == workspace_id,
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.deleted.is_(False),
    )
    if load_workspace:
        stmt = stmt.options(selectinload(WorkspaceMembership.workspace))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def require_workspace_role(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    allowed_roles: set[str],
) -> tuple[Workspace, WorkspaceMembership]:
    membership = await get_active_membership(
        db,
        workspace_id=workspace_id,
        user_id=actor.id,
        load_workspace=True,
    )
    if membership is None or membership.workspace.deleted:
        raise AuthorizationError("Workspace not found or access denied")
    if membership.role not in allowed_roles:
        raise AuthorizationError(
            "Requires higher level role",
            details={
                "allowed_roles": sorted(allowed_roles),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(workspace_id),
                "user_id": str(actor.id),
            },
        )
    return membership.workspace, membership


async def get_user_or_raise(db: AsyncSession, *, user_id: UUID) -> User:
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.deleted.is_(False),
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found", resource_type="user", resource_id=str(user_id))
    return user


async def active_owner_count(db: AsyncSession, *, workspace_id: UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == WorkspaceRole.OWNER.value,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    return int(count or 0)


async def ensure_not_last_owner(
    db: AsyncSession,
    *,
    membership: WorkspaceMembership,
) -> None:
    if membership.role != WorkspaceRole.OWNER.value:
        return
    if await active_owner_count(db, workspace_id=membership.workspace_id) <= 1:
        raise AppValidationError(
            "A workspace must keep at least one active owner",
            field="membership_id",
        )


def ensure_team_workspace(workspace: Workspace) -> None:
    if workspace.is_personal:
        raise AppValidationError("Personal workspaces cannot be shared", field="workspace_id")


async def record_workspace_security_event(
    *,
    event_type: SecurityEventType,
    request: Request,
    actor: User | None = None,
    details: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    committed: bool = False,
) -> None:
    event_kwargs = {
        "event_type": event_type,
        "ip_address": request_ip(request),
        "endpoint": request.url.path,
        "user_email": getattr(actor, "email", None),
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.scope.get("request_id") or request.headers.get("x-request-id"),
        "details": details or {},
    }
    if committed:
        await safe_record_security_event_committed(**event_kwargs)
        return
    if db is None:
        raise RuntimeError("db is required for request-scoped security events")
    await safe_record_security_event(db, **event_kwargs)
