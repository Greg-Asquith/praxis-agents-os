# apps/api/services/skills/documents/delete_document.py

"""Delete one document from a workspace skill manifest."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.skills.documents.utils import (
    best_effort_delete_private_object,
    entry_from_manifest,
)
from services.skills.utils import get_skill_for_workspace, require_skill_write_access
from services.storage.factory import get_storage_provider


async def delete_skill_document(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    skill_id: UUID,
    document_name: str,
) -> None:
    """Remove a skill document manifest entry and delete its stored objects."""
    require_skill_write_access(membership)
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    entry = entry_from_manifest(skill.documentation_refs, document_name, skill_id=skill.id)
    if entry is None:
        raise NotFoundError(
            "Skill document not found",
            resource_type="skill_document",
            resource_id=document_name,
        )

    manifest = dict(skill.documentation_refs or {})
    manifest.pop(document_name, None)
    skill.documentation_refs = manifest
    await db.flush()

    provider = get_storage_provider()
    await best_effort_delete_private_object(entry.original, provider=provider)
    await best_effort_delete_private_object(entry.markdown, provider=provider)
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.SKILL,
        resource_id=skill.id,
        actor=actor,
        details={"document": document_name, "action": "delete"},
    )
