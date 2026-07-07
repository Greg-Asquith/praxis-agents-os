# apps/api/services/files/build_attachment_user_content.py

"""Build Pydantic AI user content for chat attachments."""

from collections.abc import Sequence

from pydantic_ai.messages import BinaryContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.files import File, FileRevision
from services.files.resolve_chat_attachments import normalize_content_type
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider


async def build_attachment_user_content(
    db: AsyncSession,
    *,
    files: Sequence[File],
) -> list[BinaryContent]:
    """Read current file blobs and return ordered BinaryContent items."""
    if not files:
        return []

    revisions = (
        await db.scalars(
            select(FileRevision).where(
                FileRevision.id.in_(
                    file.current_revision_id for file in files if file.current_revision_id
                )
            )
        )
    ).all()
    revisions_by_id = {revision.id: revision for revision in revisions}
    provider = get_storage_provider()

    contents: list[BinaryContent] = []
    for file in files:
        if file.current_revision_id is None:
            raise NotFoundError(
                "File revision not found",
                resource_type="file_revision",
                details={"file_id": str(file.id)},
            )
        revision = revisions_by_id.get(file.current_revision_id)
        if revision is None:
            raise NotFoundError(
                "File revision not found",
                resource_type="file_revision",
                resource_id=str(file.current_revision_id),
            )
        contents.append(
            BinaryContent(
                data=await provider.get_object(private_ref_from_key(revision.object_key)),
                media_type=normalize_content_type(file.content_type),
                identifier=str(file.id),
            )
        )
    return contents
