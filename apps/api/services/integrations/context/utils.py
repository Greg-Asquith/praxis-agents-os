# apps/api/services/integrations/context/utils.py

"""Lookup, validation, and response helpers for integration context services."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.integration_context import IntegrationContextGroup, IntegrationContextGroupMember
from models.integrations import IntegrationConnection, IntegrationResource
from models.user import User
from models.workspace import Workspace
from services.integrations.context.schemas import ContextGroupRead

CONTEXT_GROUP_NAME_UNIQUE_CONSTRAINT = "uq_integration_context_groups_workspace_name"


def sanitize_context_error(message: str, *, max_chars: int = 1000) -> str:
    """Bound an operation error and remove control characters from model-visible text."""
    sanitized = " ".join(message.split())
    return sanitized[:max_chars]


def normalize_context_group_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise AppValidationError("Context group name cannot be blank", field="name")
    if len(normalized) > 120:
        raise AppValidationError(
            "Context group name must be 120 characters or fewer",
            field="name",
        )
    return normalized


async def load_selection_resource(
    db: AsyncSession,
    *,
    resource_id: UUID,
    actor: User,
    workspace: Workspace,
) -> IntegrationResource:
    row = (
        await db.execute(
            select(IntegrationResource, IntegrationConnection)
            .join(
                IntegrationConnection,
                IntegrationConnection.id == IntegrationResource.connection_id,
            )
            .where(IntegrationResource.id == resource_id)
        )
    ).one_or_none()
    if row is None:
        raise AppValidationError(
            "Selected integration resource does not exist",
            field="integration_resource_id",
        )
    resource, connection = row
    is_visible = (
        connection.owner_workspace_id == workspace.id or connection.owner_user_id == actor.id
    )
    if not is_visible:
        raise NotFoundError(
            "Integration resource not found",
            resource_type="integration_resource",
            resource_id=str(resource_id),
        )
    if resource.deleted or connection.deleted:
        raise AppValidationError(
            "Selected integration resource is no longer available",
            field="integration_resource_id",
        )
    return resource


async def load_selection_group(
    db: AsyncSession,
    *,
    group_id: UUID,
    workspace: Workspace,
) -> IntegrationContextGroup:
    group = await db.get(IntegrationContextGroup, group_id)
    if group is None:
        raise AppValidationError(
            "Selected context group does not exist",
            field="context_group_id",
        )
    if group.workspace_id != workspace.id:
        raise NotFoundError(
            "Context group not found",
            resource_type="integration_context_group",
            resource_id=str(group_id),
        )
    if group.deleted:
        raise AppValidationError(
            "Selected context group is no longer available",
            field="context_group_id",
        )
    return group


async def load_workspace_group(
    db: AsyncSession,
    *,
    group_id: UUID,
    workspace: Workspace,
    for_update: bool = False,
) -> IntegrationContextGroup:
    statement = (
        select(IntegrationContextGroup)
        .options(
            selectinload(IntegrationContextGroup.members).selectinload(
                IntegrationContextGroupMember.resource
            )
        )
        .where(
            IntegrationContextGroup.id == group_id,
            IntegrationContextGroup.workspace_id == workspace.id,
            IntegrationContextGroup.deleted.is_(False),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    group = await db.scalar(statement)
    if group is None:
        raise NotFoundError(
            "Context group not found",
            resource_type="integration_context_group",
            resource_id=str(group_id),
        )
    return group


async def load_workspace_resources(
    db: AsyncSession,
    *,
    resource_ids: Collection[UUID],
    actor: User,
    workspace: Workspace,
) -> list[IntegrationResource]:
    unique_ids = set(resource_ids)
    if not unique_ids:
        return []
    ownership = IntegrationConnection.owner_workspace_id == workspace.id
    if workspace.is_personal:
        ownership = or_(ownership, IntegrationConnection.owner_user_id == actor.id)
    resources = (
        await db.scalars(
            select(IntegrationResource)
            .join(
                IntegrationConnection,
                IntegrationConnection.id == IntegrationResource.connection_id,
            )
            .where(
                IntegrationResource.id.in_(unique_ids),
                IntegrationResource.deleted.is_(False),
                IntegrationConnection.deleted.is_(False),
                ownership,
            )
        )
    ).all()
    if {resource.id for resource in resources} != unique_ids:
        raise AppValidationError(
            "Resources must be available to Context Groups in the current workspace",
            field="resource_ids",
        )
    return sorted(resources, key=lambda resource: str(resource.id))


async def reload_group_read(
    db: AsyncSession,
    *,
    group_id: UUID,
    workspace: Workspace,
) -> ContextGroupRead:
    group = await load_workspace_group(db, group_id=group_id, workspace=workspace)
    return ContextGroupRead.from_group(group)


def context_group_conflict(exc: Exception) -> ConflictError | None:
    if CONTEXT_GROUP_NAME_UNIQUE_CONSTRAINT in str(exc):
        return ConflictError(
            "A context group with this name already exists in the workspace",
            conflicting_resource="integration_context_group",
        )
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    if getattr(diag, "constraint_name", None) == CONTEXT_GROUP_NAME_UNIQUE_CONSTRAINT:
        return ConflictError(
            "A context group with this name already exists in the workspace",
            conflicting_resource="integration_context_group",
        )
    return None
