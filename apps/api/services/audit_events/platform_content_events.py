# apps/api/services/audit_events/platform_content_events.py

"""Restricted, transactional audit records for platform content management."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_MAINTENANCE_KEY
from core.dependencies import require_super_admin_user
from core.exceptions.auth import AuthorizationError
from models.artifacts import Artifact
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import WorkspaceMembership
from services.artifacts.utils import can_edit_artifact
from services.audit_events.enums import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event


class PlatformContentSource(BaseModel):
    """Source identity retained only in the restricted global audit log."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: UUID
    resource_id: UUID
    revision_id: UUID


class PlatformContentAuditDetails(BaseModel):
    """Bounded metadata without content, credentials, or download capabilities."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal["platform"] = "platform"
    operation: Literal[
        "create",
        "update",
        "replace",
        "restore",
        "publish",
        "publish_revision",
        "withdraw",
        "delete",
    ]
    revision_id: UUID | None = None
    previous_revision_id: UUID | None = None
    changed_fields: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=32
    )
    source: PlatformContentSource | None = None


async def record_platform_content_audit_event(
    db: AsyncSession,
    *,
    request: Request | None,
    actor: User,
    resource_type: Literal[
        AuditResourceType.FILE, AuditResourceType.KB_DOCUMENT, AuditResourceType.ARTIFACT
    ],
    resource_id: UUID,
    details: PlatformContentAuditDetails,
    artifact: Artifact | None = None,
    membership: WorkspaceMembership | None = None,
) -> AuditEvent:
    """Writes global evidence in the mutation transaction and propagates failure."""
    if details.operation == "publish_revision":
        if (
            resource_type != AuditResourceType.ARTIFACT
            or artifact is None
            or artifact.id != resource_id
            or artifact.scope != "platform"
            or details.revision_id is None
            or not can_edit_artifact(artifact, actor=actor, membership=membership)
        ):
            raise AuthorizationError("Requires authority to edit the platform artifact")
    else:
        require_super_admin_user(actor)
    if not db.info.get(SESSION_MAINTENANCE_KEY):
        raise AuthorizationError("Platform audit requires a maintenance transaction")
    if resource_type not in (
        AuditResourceType.FILE,
        AuditResourceType.KB_DOCUMENT,
        AuditResourceType.ARTIFACT,
    ):
        raise ValueError("Unsupported platform content resource type")
    action = {
        "create": AuditAction.CREATE,
        "delete": AuditAction.DELETE,
    }.get(details.operation, AuditAction.UPDATE)
    return await record_operation_audit_event(
        db,
        workspace_id=None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        details=details.model_dump(mode="json", exclude_none=True),
        request=request,
    )
