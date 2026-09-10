# apps/api/services/files/create_file_preview.py

"""Create signed inline preview grants for workspace media files."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.workspace import Workspace
from services.files.contract import FileCategory, contract_for_content_type
from services.files.domain import FilePreviewGrant
from services.files.utils import file_revision_ref, get_visible_file, get_visible_file_revision
from services.storage.factory import get_storage_provider


async def create_file_preview(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
) -> FilePreviewGrant:
    """Create a short-lived inline preview URL without recording a file-read audit event."""
    file = await get_visible_file(db, workspace_id=workspace.id, file_id=file_id)
    revision = await get_visible_file_revision(db, workspace_id=workspace.id, file=file)
    entry = contract_for_content_type(revision.content_type)
    previewable = entry.category in {FileCategory.IMAGE, FileCategory.VIDEO} or (
        entry.content_type == "application/pdf"
    )
    if not previewable:
        raise AppValidationError(
            "Previews are available for images, videos, and PDFs",
            field="file_id",
            details={"file_id": str(file.id), "content_type": revision.content_type},
        )

    preview = await get_storage_provider().create_signed_download(
        file_revision_ref(revision),
        expires_in=timedelta(minutes=10),
        force_download=False,
        filename=file.name,
    )
    return FilePreviewGrant(preview=preview, expires_at=preview.expires_at)
