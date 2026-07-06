# apps/api/services/files/create_file_download.py

"""Create a signed download grant for a workspace file."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.files import FileRevision
from models.workspace import Workspace
from services.files.domain import FileDownloadGrant, FileDownloadRequest
from services.files.utils import get_file_for_workspace, private_ref_from_key
from services.storage.factory import get_storage_provider


async def create_file_download(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
    payload: FileDownloadRequest,
) -> FileDownloadGrant:
    """Create a short-lived signed download for the current or selected revision."""
    file = await get_file_for_workspace(db, workspace=workspace, file_id=file_id)
    revision_id = payload.revision_id or file.current_revision_id
    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == revision_id,
            FileRevision.file_id == file.id,
            FileRevision.workspace_id == workspace.id,
        )
    )
    if revision is None:
        raise NotFoundError(
            "File revision not found",
            resource_type="file_revision",
            resource_id=str(revision_id),
        )

    provider = get_storage_provider()
    download = await provider.create_signed_download(
        private_ref_from_key(revision.object_key),
        expires_in=timedelta(minutes=10),
        force_download=payload.force_download,
        filename=file.name,
    )
    return FileDownloadGrant(download=download, expires_at=download.expires_at)
