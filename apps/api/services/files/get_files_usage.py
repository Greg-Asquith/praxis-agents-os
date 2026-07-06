# apps/api/services/files/get_files_usage.py

"""Workspace file storage usage counter."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import File, FileRevision
from models.workspace import Workspace
from services.files.domain import FilesUsageResponse


async def get_files_usage(
    db: AsyncSession,
    *,
    workspace: Workspace,
) -> FilesUsageResponse:
    """Return distinct stored bytes for workspace files; this is not a hard quota."""
    rows = (
        await db.execute(
            select(
                FileRevision.object_key,
                FileRevision.size_bytes,
                FileRevision.markdown_object_key,
                FileRevision.markdown_size_bytes,
            )
            .join(File, File.id == FileRevision.file_id)
            .where(File.workspace_id == workspace.id)
        )
    ).all()

    sizes_by_key: dict[str, int] = {}
    for object_key, size_bytes, markdown_object_key, markdown_size_bytes in rows:
        sizes_by_key.setdefault(object_key, int(size_bytes))
        if markdown_object_key:
            sizes_by_key.setdefault(markdown_object_key, int(markdown_size_bytes or 0))

    used_bytes = sum(sizes_by_key.values())
    soft_limit = settings.FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES
    return FilesUsageResponse(
        used_bytes=used_bytes,
        soft_limit_bytes=soft_limit,
        over_soft_limit=used_bytes > soft_limit,
    )
