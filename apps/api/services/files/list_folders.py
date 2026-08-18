# apps/api/services/files/list_folders.py

"""List workspace file folders with live-file aggregates."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileFolder
from models.workspace import Workspace
from services.files.domain import FileFolderListResponse, FileFolderRead


async def list_folders(db: AsyncSession, *, workspace: Workspace) -> FileFolderListResponse:
    counts = (
        select(
            File.folder_id.label("folder_id"),
            func.count(File.id).label("file_count"),
            func.coalesce(func.sum(File.size_bytes), 0).label("total_bytes"),
            func.max(File.updated_at).label("latest_file_updated_at"),
        )
        .where(
            File.workspace_id == workspace.id,
            File.folder_id.is_not(None),
            File.deleted.is_(False),
        )
        .group_by(File.folder_id)
        .subquery()
    )
    activity_at = func.greatest(
        FileFolder.updated_at,
        func.coalesce(counts.c.latest_file_updated_at, FileFolder.updated_at),
    )
    rows = (
        await db.execute(
            select(
                FileFolder,
                func.coalesce(counts.c.file_count, 0),
                func.coalesce(counts.c.total_bytes, 0),
                activity_at.label("activity_at"),
            )
            .outerjoin(counts, counts.c.folder_id == FileFolder.id)
            .where(
                FileFolder.workspace_id == workspace.id,
                FileFolder.deleted.is_(False),
            )
            .order_by(activity_at.desc(), FileFolder.id.desc())
        )
    ).all()
    return FileFolderListResponse(
        folders=[
            FileFolderRead(
                id=folder.id,
                workspace_id=folder.workspace_id,
                name=folder.name,
                description=folder.description,
                file_count=int(file_count),
                total_bytes=int(total_bytes),
                created_at=folder.created_at,
                updated_at=activity_at,
            )
            for folder, file_count, total_bytes, activity_at in rows
        ]
    )
