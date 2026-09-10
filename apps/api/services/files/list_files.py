# apps/api/services/files/list_files.py

"""List workspace files."""

from typing import Literal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.files import File, FileFolder, FileRevision
from models.workspace import Workspace
from services.files.contract import FileCategory
from services.files.domain import FileListResponse
from services.files.utils import (
    file_for_revision,
    file_name_search_filter,
    file_sort_column,
    file_to_read,
)
from services.files.visibility import visible_file_filter, visible_file_revision_filter


async def list_files(
    db: AsyncSession,
    *,
    workspace: Workspace,
    scope: Literal["all", "workspace", "platform"] = "all",
    category: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
    limit: int = 50,
    offset: int = 0,
    folder_id: UUID | None = None,
    root_only: bool = False,
) -> FileListResponse:
    """List non-deleted files in a workspace."""
    selected_revision = case(
        (File.scope == "platform", File.published_revision_id),
        else_=File.current_revision_id,
    )
    stmt = (
        select(File)
        .outerjoin(FileRevision, FileRevision.id == selected_revision)
        .where(
            visible_file_filter(workspace.id),
            (File.scope == "workspace") | visible_file_revision_filter(workspace.id),
        )
    )
    if scope != "all":
        stmt = stmt.where(File.scope == scope)
    if folder_id is not None and root_only:
        raise AppValidationError("folder_id and root_only cannot be combined", field="folder_id")
    if folder_id is not None:
        stmt = stmt.where(File.folder_id == folder_id)
    elif root_only:
        stmt = stmt.where(File.folder_id.is_(None))
    if category is not None:
        try:
            normalized_category = FileCategory(category).value
        except ValueError as exc:
            raise AppValidationError("Unknown file category", field="category") from exc
        stmt = stmt.where(File.category == normalized_category)
    if search:
        stmt = stmt.where(file_name_search_filter(search))

    sort_column = file_sort_column(sort_by, sort_direction)

    if sort_by in {"extension", "size_bytes", "updated_at", "processing_status"}:
        published_value = {
            "extension": FileRevision.extension,
            "size_bytes": FileRevision.size_bytes,
            "updated_at": FileRevision.created_at,
            "processing_status": "ready",
        }[sort_by]
        sort_column = case((File.scope == "platform", published_value), else_=sort_column)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    order = sort_column.asc() if sort_direction == "asc" else sort_column.desc()
    id_order = File.id.asc() if sort_direction == "asc" else File.id.desc()
    rows = (
        await db.execute(
            stmt.add_columns(FileFolder.name, FileRevision)
            .outerjoin(
                FileFolder,
                (FileFolder.id == File.folder_id)
                & (FileFolder.workspace_id == workspace.id)
                & FileFolder.deleted.is_(False),
            )
            .order_by(order, id_order)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = await db.scalar(count_stmt)
    return FileListResponse(
        files=[
            file_to_read(file_for_revision(file, revision), folder_name=folder_name)
            for file, folder_name, revision in rows
        ],
        total=int(total or 0),
    )
