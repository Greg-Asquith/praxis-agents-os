# apps/api/services/files/platform/list_files.py

"""Lists live platform Files for super-admin review."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File
from models.user import User
from services.files.domain import FileListResponse
from services.files.platform.utils import platform_file_to_read, platform_session
from utils.content import ContentScope


async def list_files(
    db: AsyncSession, *, actor: User, limit: int = 50, offset: int = 0
) -> FileListResponse:
    async with platform_session(db, actor) as maintenance_db:
        predicates = (
            File.scope == ContentScope.PLATFORM,
            File.workspace_id.is_(None),
            File.deleted.is_(False),
        )
        total = await maintenance_db.scalar(
            select(func.count()).select_from(File).where(*predicates)
        )
        files = await maintenance_db.scalars(
            select(File)
            .where(*predicates)
            .order_by(File.created_at.desc(), File.id)
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
        return FileListResponse(
            files=[platform_file_to_read(file, actor) for file in files], total=total or 0
        )
