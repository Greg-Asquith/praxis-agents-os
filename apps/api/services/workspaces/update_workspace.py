# apps/api/services/workspaces/update_workspace.py

"""Update workspace metadata."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.workspaces.schemas import WorkspaceRead, WorkspaceUpdateRequest
from services.workspaces.utils import (
    MANAGER_ROLES,
    require_workspace_role,
)
from utils.slugify import slugify


async def update_workspace(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    payload: WorkspaceUpdateRequest,
) -> WorkspaceRead:
    workspace, membership = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    changed_fields: list[str] = []

    if "name" in payload.model_fields_set:
        if payload.name is None:
            raise AppValidationError("name cannot be null", field="name")
        if payload.name != workspace.name:
            workspace.name = payload.name
            changed_fields.append("name")

    if "icon_url" in payload.model_fields_set and payload.icon_url != workspace.icon_url:
        workspace.icon_url = payload.icon_url
        changed_fields.append("icon_url")

    if "slug" in payload.model_fields_set:
        if payload.slug is None:
            raise AppValidationError("slug cannot be null", field="slug")
        normalized_slug = slugify(payload.slug, max_length=100) or "workspace"
        if normalized_slug != workspace.slug:
            existing = await db.scalar(
                select(Workspace.id).where(
                    Workspace.slug == normalized_slug,
                    Workspace.id != workspace.id,
                    Workspace.deleted.is_(False),
                )
            )
            if existing is not None:
                raise ConflictError(
                    "A workspace with that slug already exists",
                    conflicting_resource="workspace",
                )
            workspace.slug = normalized_slug
            changed_fields.append("slug")

    if changed_fields:
        try:
            await db.flush()
        except IntegrityError as exc:
            raise ConflictError(
                "A workspace with that slug already exists",
                conflicting_resource="workspace",
            ) from exc
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.WORKSPACE,
            resource_id=workspace.id,
            actor=actor,
            details={"fields": changed_fields, "slug": workspace.slug},
        )

    return WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)
