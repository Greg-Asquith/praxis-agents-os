# apps/api/services/classifiers/delete_classifier.py

"""Delete a workspace classifier definition."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.classifiers.utils import get_classifier_for_workspace, require_classifier_write_access


async def delete_classifier(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    classifier_id: UUID,
) -> None:
    require_classifier_write_access(membership)
    classifier = await get_classifier_for_workspace(
        db, workspace=workspace, classifier_id=classifier_id
    )
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.CLASSIFIER,
        resource_id=classifier.id,
        actor=actor,
        details={"classifier_name": classifier.name},
    )
    await db.delete(classifier)
    await db.flush()
