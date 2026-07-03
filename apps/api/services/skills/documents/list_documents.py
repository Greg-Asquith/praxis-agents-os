# apps/api/services/skills/documents/list_documents.py

"""List uploaded documents for a workspace skill."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.skills.documents.domain import SkillDocumentRead, SkillDocumentsListResponse
from services.skills.documents.utils import parse_manifest_entry
from services.skills.utils import get_skill_for_workspace


async def list_skill_documents(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_id: UUID,
) -> SkillDocumentsListResponse:
    """Return parsed skill document manifest entries."""
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    documents: list[SkillDocumentRead] = []
    for name, value in sorted((skill.documentation_refs or {}).items()):
        entry = parse_manifest_entry(name, value, skill_id=skill.id)
        if entry is not None:
            documents.append(SkillDocumentRead(name=name, **entry.model_dump()))
    return SkillDocumentsListResponse(documents=documents, total=len(documents))
