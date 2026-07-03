# apps/api/services/skills/documents/get_document_markdown.py

"""Read converted markdown for a skill document."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.workspace import Workspace
from services.skills.documents.domain import SkillDocumentMarkdownResponse
from services.skills.documents.utils import (
    TRUNCATION_MARKER,
    entry_from_manifest,
    private_ref_from_key,
)
from services.skills.utils import get_skill_for_workspace
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider


async def get_skill_document_markdown(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_id: UUID,
    document_name: str,
) -> SkillDocumentMarkdownResponse:
    """Return converted markdown content for one ready skill document."""
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    entry = entry_from_manifest(skill.documentation_refs, document_name, skill_id=skill.id)
    if entry is None or entry.status != "ready" or not entry.markdown:
        raise NotFoundError(
            "Skill document markdown not found",
            resource_type="skill_document",
            resource_id=document_name,
        )

    provider = get_storage_provider()
    try:
        data = await provider.get_object(private_ref_from_key(entry.markdown))
    except StorageNotFoundError as exc:
        raise NotFoundError(
            "Skill document markdown not found",
            resource_type="skill_document",
            resource_id=document_name,
        ) from exc
    content = data.decode("utf-8", errors="replace")
    return SkillDocumentMarkdownResponse(
        name=document_name,
        content=content,
        truncated=TRUNCATION_MARKER in content,
    )
