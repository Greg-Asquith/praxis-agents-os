# apps/api/services/files/create_file_preview.py

"""Create signed inline preview grants for workspace image files."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.files import FileRevision
from models.workspace import Workspace
from services.files.contract import FileCategory, contract_for_content_type
from services.files.domain import FilePreviewGrant
from services.files.utils import get_file_for_workspace, private_ref_from_key
from services.storage.factory import get_storage_provider


async def create_file_preview(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
) -> FilePreviewGrant:
    """Create a short-lived inline preview URL without recording a file-read audit event."""
    file = await get_file_for_workspace(db, workspace=workspace, file_id=file_id)
    entry = contract_for_content_type(file.content_type)
    if entry.category != FileCategory.IMAGE:
        raise AppValidationError(
            "Only image files can be previewed",
            field="file_id",
            details={"file_id": str(file.id), "content_type": file.content_type},
        )

    revision = await db.scalar(
        select(FileRevision).where(
            FileRevision.id == file.current_revision_id,
            FileRevision.file_id == file.id,
            FileRevision.workspace_id == workspace.id,
        )
    )
    if revision is None:
        raise NotFoundError(
            "File revision not found",
            resource_type="file_revision",
            resource_id=str(file.current_revision_id),
        )

    preview = await get_storage_provider().create_signed_download(
        private_ref_from_key(revision.object_key),
        expires_in=timedelta(minutes=10),
        force_download=False,
        filename=file.name,
    )
    return FilePreviewGrant(preview=preview, expires_at=preview.expires_at)
