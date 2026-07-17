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

_SORT_COLUMNS = {
    "created_at": File.created_at,
    "extension": File.extension,
    "name": File.name,
    "processing_status": File.processing_status,
    "size_bytes": File.size_bytes,
    "updated_at": File.updated_at,
}


async def list_files(
    db: AsyncSession,
    *,
    workspace: Workspace,
    category: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> FileListResponse:
    """List non-deleted files in a workspace."""
    stmt = select(File).where(File.workspace_id == workspace.id, File.deleted.is_(False))
    count_stmt = (
        select(func.count())
        .select_from(File)
        .where(
            File.workspace_id == workspace.id,
            File.deleted.is_(False),
        )
    )
    if category is not None:
        try:
            normalized_category = FileCategory(category).value
        except ValueError as exc:
            raise AppValidationError("Unknown file category", field="category") from exc
        stmt = stmt.where(File.category == normalized_category)
        count_stmt = count_stmt.where(File.category == normalized_category)
    if search:
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(File.name.ilike(pattern, escape="\\"))
        count_stmt = count_stmt.where(File.name.ilike(pattern, escape="\\"))

    sort_column = _SORT_COLUMNS.get(sort_by)
    if sort_column is None:
        raise AppValidationError("Unknown file sort field", field="sort_by")
    if sort_direction not in {"asc", "desc"}:
        raise AppValidationError("Unknown file sort direction", field="sort_direction")

    order = sort_column.asc() if sort_direction == "asc" else sort_column.desc()
    id_order = File.id.asc() if sort_direction == "asc" else File.id.desc()
    files = (await db.scalars(stmt.order_by(order, id_order).limit(limit).offset(offset))).all()
    total = await db.scalar(count_stmt)
    return FileListResponse(files=[file_to_read(file) for file in files], total=int(total or 0))
