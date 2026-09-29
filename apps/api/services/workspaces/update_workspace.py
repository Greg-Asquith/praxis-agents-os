# apps/api/services/workspaces/update_workspace.py

"""Update workspace metadata."""

from typing import Any
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
    validate_default_model,
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
    audit_details: dict[str, Any] = {}

    if "conversations_shared_by_default" in payload.model_fields_set:
        if workspace.is_personal:
            raise AppValidationError(
                "Personal workspaces cannot share conversations by default",
                field="conversations_shared_by_default",
            )
        if payload.conversations_shared_by_default is None:
            raise AppValidationError(
                "conversations_shared_by_default cannot be null",
                field="conversations_shared_by_default",
            )
        if payload.conversations_shared_by_default != workspace.conversations_shared_by_default:
            audit_details["conversations_shared_by_default"] = {
                "previous": workspace.conversations_shared_by_default,
                "value": payload.conversations_shared_by_default,
            }
            workspace.conversations_shared_by_default = payload.conversations_shared_by_default
            changed_fields.append("conversations_shared_by_default")

    if payload.model_fields_set & {"default_model_provider", "default_model"}:
        previous = (workspace.default_model_provider, workspace.default_model)
        requested = (payload.default_model_provider, payload.default_model)
        # Resubmitting the saved pair must not block unrelated edits after a provider change.
        if requested != previous:
            validate_default_model(*requested)
            audit_details["default_model"] = {
                "previous": "/".join(previous) if previous[0] else None,
                "value": "/".join(requested) if requested[0] else None,
            }
            workspace.default_model_provider, workspace.default_model = requested
            changed_fields.append("default_model")

    if "name" in payload.model_fields_set:
        if payload.name is None:
            raise AppValidationError("name cannot be null", field="name")
        if payload.name != workspace.name:
            workspace.name = payload.name
            changed_fields.append("name")

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
            details={"fields": changed_fields, "slug": workspace.slug, **audit_details},
        )
        await db.refresh(workspace)

    return WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)
