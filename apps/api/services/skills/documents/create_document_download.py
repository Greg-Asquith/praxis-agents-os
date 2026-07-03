# apps/api/services/skills/documents/create_document_download.py

"""Create a signed download for a skill document original."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.workspace import Workspace
from services.skills.documents.utils import entry_from_manifest, private_ref_from_key
from services.skills.utils import get_skill_for_workspace
from services.storage.domain import SignedDownload
from services.storage.factory import get_storage_provider


async def create_skill_document_download(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_id: UUID,
    document_name: str,
) -> SignedDownload:
    """Return a signed download for a skill document's original object."""
    skill = await get_skill_for_workspace(db, workspace=workspace, skill_id=skill_id)
    entry = entry_from_manifest(skill.documentation_refs, document_name, skill_id=skill.id)
    if entry is None:
        raise NotFoundError(
            "Skill document not found",
            resource_type="skill_document",
            resource_id=document_name,
        )
    provider = get_storage_provider()
    return await provider.create_signed_download(
        private_ref_from_key(entry.original),
        expires_in=timedelta(minutes=10),
        force_download=True,
        filename=entry.filename,
    )
