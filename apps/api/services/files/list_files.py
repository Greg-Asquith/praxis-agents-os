# apps/api/services/files/list_files.py

"""List workspace files."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.files import File
from models.workspace import Workspace
from services.files.contract import FileCategory
from services.files.domain import FileListResponse
from services.files.utils import file_to_read


async def list_files(
    db: AsyncSession,
    *,
    workspace: Workspace,
    category: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FileListResponse:
    """List non-deleted files in a workspace."""
    stmt = select(File).where(File.workspace_id == workspace.id, File.deleted.is_(False))
    count_stmt = select(func.count()).select_from(File).where(
        File.workspace_id == workspace.id,
        File.deleted.is_(False),
    )
    if category is not None:
        try:
            normalized_category = FileCategory(category).value
        except ValueError as exc:
            raise AppValidationError("Unknown file category", field="category") from exc
        stmt = stmt.where(File.category == normalized_category)
        count_stmt = count_stmt.where(File.category == normalized_category)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(File.name.ilike(pattern))
        count_stmt = count_stmt.where(File.name.ilike(pattern))

    files = (
        await db.scalars(
            stmt.order_by(File.created_at.desc(), File.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    total = await db.scalar(count_stmt)
    return FileListResponse(files=[file_to_read(file) for file in files], total=int(total or 0))
