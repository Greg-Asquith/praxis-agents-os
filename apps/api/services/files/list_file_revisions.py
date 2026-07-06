# apps/api/services/files/list_file_revisions.py

"""List revisions for one workspace file."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from models.workspace import Workspace
from services.files.domain import FileRevisionsListResponse
from services.files.utils import get_file_for_workspace, revision_to_read


async def list_file_revisions(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
) -> FileRevisionsListResponse:
    """Return immutable revisions for a workspace file, newest first."""
    await get_file_for_workspace(db, workspace=workspace, file_id=file_id)
    revisions = (
        await db.scalars(
            select(FileRevision)
            .where(FileRevision.file_id == file_id, FileRevision.workspace_id == workspace.id)
            .order_by(FileRevision.revision_number.desc())
        )
    ).all()
    return FileRevisionsListResponse(
        revisions=[revision_to_read(revision) for revision in revisions],
        total=len(revisions),
    )
