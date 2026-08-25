# apps/api/services/files/build_attachment_user_content.py

"""Build Pydantic AI user content for chat attachments."""

import asyncio
from collections.abc import Sequence

from pydantic_ai.messages import BinaryContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from models.files import File, FileRevision
from services.assets.utils import normalize_content_type
from services.files.attachment_text import attachment_text_payload, markdown_for_revision
from services.files.contract import FileCategory, contract_for_content_type
from services.files.resolve_chat_attachments import PDF_MEDIA_TYPE
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider
from utils.document_markdown import DocumentConversionError


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
        contents.append(await _build_revision_content(file=file, revision=revision))
    return contents


async def _build_revision_content(*, file: File, revision: FileRevision) -> BinaryContent:
    media_type = normalize_content_type(revision.content_type)
    category = contract_for_content_type(media_type).category
    if category == FileCategory.IMAGE or media_type == PDF_MEDIA_TYPE:
        provider = get_storage_provider()
        return BinaryContent(
            data=await provider.get_object(private_ref_from_key(revision.object_key)),
            media_type=media_type,
            identifier=str(file.id),
        )

    try:
        markdown = await asyncio.wait_for(
            markdown_for_revision(
                file,
                revision,
                max_bytes=settings.FILES_MAX_MARKDOWN_BYTES,
            ),
            timeout=settings.CHAT_ATTACHMENT_CONVERSION_TIMEOUT_SECONDS,
        )
    except (TimeoutError, DocumentConversionError) as exc:
        raise AppValidationError(
            "The attached document couldn't be read. Try again, or ask the agent to open it "
            "with run_code.",
            field="attachments",
            details={"file_id": str(file.id), "content_type": media_type},
        ) from exc

    return BinaryContent(
        data=attachment_text_payload(file, revision, markdown),
        media_type="text/plain",
        identifier=str(file.id),
    )
