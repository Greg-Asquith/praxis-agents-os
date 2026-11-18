# apps/api/services/email_suppressions/remove_email_suppression.py

"""Remove one address from the workspace Do Not Email list."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.email_suppression import WorkspaceEmailSuppression
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def remove_email_suppression(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    suppression_id: UUID,
) -> None:
    entry = await db.scalar(
        select(WorkspaceEmailSuppression).where(
            WorkspaceEmailSuppression.id == suppression_id,
            WorkspaceEmailSuppression.workspace_id == workspace.id,
        )
    )
    if entry is None:
        raise NotFoundError(
            "Address not found on the Do Not Email list",
            resource_type="email_suppression",
            resource_id=str(suppression_id),
        )
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.EMAIL_SUPPRESSION,
        resource_id=entry.id,
        actor=actor,
        details={"email": entry.email, "reason": entry.reason},
    )
    await db.delete(entry)
    await db.flush()
