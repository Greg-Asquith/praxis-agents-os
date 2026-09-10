# apps/api/services/files/platform/list_file_revisions.py

"""Lists platform File history for authenticated review."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileRevision
from models.user import User
from services.files.domain import FileRevisionsListResponse
from services.files.platform.utils import get_platform_file, platform_session
from services.files.utils import revision_to_read
from utils.content import ContentScope


async def list_file_revisions(
    db: AsyncSession, *, actor: User, file_id: UUID, limit: int = 50, offset: int = 0
) -> FileRevisionsListResponse:
    async with platform_session(db, actor) as maintenance_db:
        file = await get_platform_file(maintenance_db, file_id=file_id)
        predicates = (
            FileRevision.file_id == file.id,
            FileRevision.scope == ContentScope.PLATFORM,
            FileRevision.workspace_id.is_(None),
        )
        total = await maintenance_db.scalar(
            select(func.count()).select_from(FileRevision).where(*predicates)
        )
        revisions = await maintenance_db.scalars(
            select(FileRevision)
            .where(*predicates)
            .order_by(FileRevision.revision_number.desc())
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
        return FileRevisionsListResponse(
            revisions=[revision_to_read(revision) for revision in revisions], total=total or 0
        )
