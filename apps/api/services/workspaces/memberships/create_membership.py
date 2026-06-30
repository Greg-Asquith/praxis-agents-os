# apps/api/services/workspaces/memberships/create_membership.py

"""Create or restore a workspace membership for an existing user."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.security import SecurityEventType
from services.workspaces.schemas import (
    WorkspaceMembershipCreateRequest,
    WorkspaceMembershipRead,
)
from services.workspaces.utils import (
    MANAGER_ROLES,
    ensure_team_workspace,
    get_user_or_raise,
    record_workspace_security_event,
    require_workspace_role,
)


async def create_membership(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    payload: WorkspaceMembershipCreateRequest,
) -> WorkspaceMembershipRead:
    workspace, _ = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    ensure_team_workspace(workspace)
    user = await get_user_or_raise(db, user_id=payload.user_id)

    existing = await db.execute(
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.user))
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
        .with_for_update()
    )
    membership = existing.scalar_one_or_none()
    if membership and not membership.deleted:
        raise ConflictError(
            "User is already a member of this workspace",
            conflicting_resource="workspace_membership",
        )

    role = payload.role.value
    if membership and membership.deleted:
        membership.restore(cascade=False)
        membership.role = role
    else:
        membership = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=user.id,
            role=role,
        )
        membership.user = user
        db.add(membership)

    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "User is already a member of this workspace",
            conflicting_resource="workspace_membership",
        ) from exc

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace_id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.WORKSPACE_MEMBERSHIP,
        resource_id=membership.id,
        actor=actor,
        details={"user_id": str(user.id), "role": role},
    )
    await record_workspace_security_event(
        db=db,
        event_type=SecurityEventType.WORKSPACE_MEMBERSHIP_CREATED,
        request=request,
        actor=actor,
        details={
            "workspace_id": str(workspace_id),
            "membership_id": str(membership.id),
            "user_id": str(user.id),
            "role": role,
        },
    )
    await db.refresh(membership)
    membership.user = user
    return WorkspaceMembershipRead.from_membership(membership)
