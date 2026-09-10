# apps/api/services/files/list_file_revisions.py

"""List revisions for one workspace file."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from models.workspace import Workspace
from services.files.domain import FileRevisionsListResponse
from services.files.utils import get_visible_file, revision_to_read
from services.files.visibility import visible_file_revision_filter


async def list_file_revisions(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
) -> FileRevisionsListResponse:
    """Return immutable revisions for a workspace file, newest first."""
    await get_visible_file(db, workspace_id=workspace.id, file_id=file_id)
    revisions = (
        await db.scalars(
            select(FileRevision)
            .where(FileRevision.file_id == file_id, visible_file_revision_filter(workspace.id))
            .order_by(FileRevision.revision_number.desc())
        )
    ).all()
    return FileRevisionsListResponse(
        revisions=[revision_to_read(revision) for revision in revisions],
        total=len(revisions),
    )
