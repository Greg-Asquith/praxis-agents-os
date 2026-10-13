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
                FileRevision.transcript_object_key,
                FileRevision.transcript_size_bytes,
            )
            .join(File, File.id == FileRevision.file_id)
            .where(
                File.workspace_id == workspace.id,
                File.scope == "workspace",
                FileRevision.workspace_id == workspace.id,
                FileRevision.scope == "workspace",
            )
        )
    ).all()

    sizes_by_key: dict[str, int] = {}
    for row in rows:
        sizes_by_key.setdefault(row.object_key, int(row.size_bytes))
        for key, size in (
            (row.markdown_object_key, row.markdown_size_bytes),
            (row.transcript_object_key, row.transcript_size_bytes),
        ):
            if key:
                sizes_by_key.setdefault(key, int(size or 0))

    used_bytes = sum(sizes_by_key.values())
    soft_limit = settings.FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES
    return FilesUsageResponse(
        used_bytes=used_bytes,
        soft_limit_bytes=soft_limit,
        over_soft_limit=used_bytes > soft_limit,
    )
