# apps/api/services/workspaces/create_workspace.py

"""Create a team workspace for the authenticated user."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.workspaces.schemas import WorkspaceCreateRequest, WorkspaceRead
from utils.slugify import slugify


async def create_workspace(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    payload: WorkspaceCreateRequest,
) -> WorkspaceRead:
    base_slug = slugify(payload.slug or payload.name, max_length=100) or "workspace"
    workspace: Workspace | None = None
    slug_was_supplied = payload.slug is not None

    for counter in range(1, 11):
        candidate_slug = base_slug if counter == 1 else f"{base_slug}-{counter}"
        candidate = Workspace(
            slug=candidate_slug,
            name=payload.name,
            icon_url=payload.icon_url,
            is_personal=False,
            status="active",
        )
        db.add(candidate)
        try:
            async with db.begin_nested():
                await db.flush([candidate])
        except IntegrityError as exc:
            db.expunge(candidate)
            if slug_was_supplied:
                raise ConflictError(
                    "A workspace with that slug already exists",
                    conflicting_resource="workspace",
                ) from exc
            continue
        workspace = candidate
        break

    if workspace is None:
        raise ConflictError(
            "Could not generate a unique workspace slug",
            conflicting_resource="workspace",
        )

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.OWNER.value,
    )
    db.add(membership)
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.WORKSPACE,
        resource_id=workspace.id,
        actor=actor,
        details={
            "slug": workspace.slug,
            "is_personal": False,
            "owner_membership_id": str(membership.id),
        },
    )
    return WorkspaceRead.from_workspace(
        workspace,
        current_user_role=WorkspaceRole.OWNER,
    )
