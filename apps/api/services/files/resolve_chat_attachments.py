# apps/api/services/files/resolve_chat_attachments.py

"""Resolve and validate files attached to a chat message."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from models.agent import Agent
from models.files import File
from services.agents.models.registry import get_model
from services.agents.models.resolution import resolve_agent_model
from services.assets.utils import normalize_content_type
from services.files.contract import FileCategory, contract_for_content_type

# Probed against pydantic-ai 2.1.0 in plan 036: these are the media
# types we send to the model, independent of the broader workspace file contract.
IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
DOCUMENT_MEDIA_TYPES = frozenset(
    {
        "application/msword",
        "application/pdf",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/csv",
        "text/html",
        "text/markdown",
        "text/plain",
    }
)


async def resolve_chat_attachments(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    agent: Agent,
    file_ids: Sequence[UUID],
) -> list[File]:
    """Load, order, and validate chat attachment files for one agent turn."""
    deduped_file_ids = _dedupe_file_ids(file_ids)
    if not deduped_file_ids:
        return []
    if len(deduped_file_ids) > settings.MAX_CHAT_ATTACHMENTS:
        raise AppValidationError(
            "Too many chat attachments",
            field="attachments",
            details={
                "max_attachments": settings.MAX_CHAT_ATTACHMENTS,
                "attachment_count": len(deduped_file_ids),
            },
        )

    files = (
        await db.scalars(
            select(File).where(
                File.id.in_(deduped_file_ids),
                File.workspace_id == workspace_id,
                File.deleted == False,  # noqa: E712
            )
        )
    ).all()
    files_by_id = {file.id: file for file in files}
    ordered_files: list[File] = []
    for file_id in deduped_file_ids:
        file = files_by_id.get(file_id)
        if file is None:
            raise NotFoundError(
                "File not found",
                resource_type="file",
                resource_id=str(file_id),
            )
        _validate_chat_attachment(file, agent=agent)
        ordered_files.append(file)
    return ordered_files


def _dedupe_file_ids(file_ids: Sequence[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    deduped: list[UUID] = []
    for file_id in file_ids:
        if file_id in seen:
            continue
        seen.add(file_id)
        deduped.append(file_id)
    return deduped


def _validate_chat_attachment(file: File, *, agent: Agent) -> None:
    entry = contract_for_content_type(file.content_type)
    media_type = normalize_content_type(file.content_type)
    if entry.category == FileCategory.IMAGE:
        _validate_image_attachment(file, media_type=media_type, agent=agent)
        return
    if entry.category in {FileCategory.INGESTIBLE_DOCUMENT, FileCategory.EDITABLE_TEXT}:
        _validate_document_attachment(file, media_type=media_type)
        return

    raise AppValidationError(
        "File type cannot be attached to chat",
        field="attachments",
        details={
            "file_id": str(file.id),
            "content_type": file.content_type,
            "category": entry.category.value,
        },
    )


def _validate_image_attachment(file: File, *, media_type: str, agent: Agent) -> None:
    if media_type not in IMAGE_MEDIA_TYPES:
        raise AppValidationError(
            "Image type is not supported for chat attachments",
            field="attachments",
            details={"file_id": str(file.id), "content_type": file.content_type},
        )
    if file.size_bytes > settings.MAX_FILE_SIZE_IMAGE:
        raise AppValidationError(
            "Image attachment is too large",
            field="attachments",
            details={
                "file_id": str(file.id),
                "size_bytes": file.size_bytes,
                "max_size_bytes": settings.MAX_FILE_SIZE_IMAGE,
            },
        )

    resolved_model = resolve_agent_model(agent)
    model_info = get_model(resolved_model.provider, resolved_model.model)
    if not model_info.supports_vision:
        raise AppValidationError(
            f"{model_info.display_name} does not support image attachments",
            field="attachments",
            details={
                "file_id": str(file.id),
                "model": model_info.qualified_id,
                "display_name": model_info.display_name,
            },
        )


def _validate_document_attachment(file: File, *, media_type: str) -> None:
    if media_type not in DOCUMENT_MEDIA_TYPES:
        raise AppValidationError(
            "Document type is not supported for chat attachments",
            field="attachments",
            details={"file_id": str(file.id), "content_type": file.content_type},
        )
    if file.size_bytes > settings.MAX_MULTIMODAL_DOCUMENT_BYTES:
        raise AppValidationError(
            "Document attachment is too large",
            field="attachments",
            details={
                "file_id": str(file.id),
                "size_bytes": file.size_bytes,
                "max_size_bytes": settings.MAX_MULTIMODAL_DOCUMENT_BYTES,
            },
        )
