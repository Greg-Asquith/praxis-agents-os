# apps/api/services/kb/documents/utils.py

"""Shared helpers for knowledge-base document management."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import NotFoundError
from models.kb import KBDocument
from models.user import User
from models.workspace import WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.kb.write_policy import KBProvenance
from services.workspaces.utils import EDITOR_ROLES


def require_kb_write_access(membership: WorkspaceMembership) -> None:
    """Require member-or-higher access for knowledge document mutations."""
    if membership.role not in EDITOR_ROLES:
        raise AuthorizationError(
            "Requires workspace write access",
            details={
                "allowed_roles": sorted(EDITOR_ROLES),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(membership.workspace_id),
                "user_id": str(membership.user_id),
            },
        )


def user_provenance(
    *,
    user_id: UUID,
    source_type: str,
    origin_ref: str | None = None,
) -> KBProvenance:
    return KBProvenance(
        actor_kind="user",
        user_id=user_id,
        source_type=source_type,
        origin_ref=origin_ref,
    )


async def get_mutable_document(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    document_id: UUID,
) -> KBDocument:
    """Load one editable visible document without leaking hidden existence."""
    document = await db.scalar(
        select(KBDocument)
        .where(
            KBDocument.id == document_id,
            KBDocument.workspace_id == workspace_id,
            KBDocument.deleted.is_(False),
            or_(
                KBDocument.is_private.is_(False),
                KBDocument.created_by_user_id == user_id,
            ),
        )
        .with_for_update()
    )
    if document is None:
        raise NotFoundError(
            "Knowledge-base document not found",
            resource_type="kb_document",
            resource_id=str(document_id),
        )
    return document


async def record_document_audit(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    document: KBDocument,
    action: AuditAction,
    details: dict[str, object],
) -> None:
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=document.workspace_id,
        action=action,
        resource_type=AuditResourceType.KB_DOCUMENT,
        resource_id=document.id,
        actor=actor,
        details=details,
    )
