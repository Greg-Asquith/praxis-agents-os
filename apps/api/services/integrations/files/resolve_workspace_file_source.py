# apps/api/services/integrations/files/resolve_workspace_file_source.py

"""Resolves current workspace File revisions for integration sources."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.files import File, FileRevision
from services.files.utils import get_visible_file, get_visible_file_revision
from utils.content import ContentScope


async def resolve_workspace_file_source(
    db: AsyncSession, *, workspace_id: UUID, file_id: UUID
) -> tuple[File, FileRevision]:
    """Returns a live workspace File and its current visible revision."""
    file = await get_visible_file(db, workspace_id=workspace_id, file_id=file_id)
    await db.refresh(file)
    if file.scope != ContentScope.WORKSPACE or file.workspace_id != workspace_id or file.deleted:
        raise NotFoundError("File not found")
    revision = await get_visible_file_revision(db, workspace_id=workspace_id, file=file)
    return file, revision
