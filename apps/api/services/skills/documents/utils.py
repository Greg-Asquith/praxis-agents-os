# apps/api/services/skills/documents/utils.py

"""Helpers for skill document storage, conversion, and manifest parsing."""

import asyncio
import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from pydantic import ValidationError

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.assets.utils import normalize_content_type, parse_content_types
from services.skills.documents.domain import (
    SKILL_DOC_NAME_PATTERN,
    SkillDocumentConversionError,
    SkillDocumentEntry,
)
from services.storage.domain import StorageBucket, StorageObjectRef, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.paths import safe_filename, validate_object_key
from services.storage.provider import StorageProvider

logger = logging.getLogger(__name__)

TRUNCATION_MARKER = "\n\n[Truncated: document exceeds the converted size limit.]"
_TEXT_CONTENT_TYPES = frozenset({"text/plain", "text/markdown"})
_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


@dataclass(frozen=True)
class ParsedSkillDocumentKey:
    """Parts encoded in a skill document original object key."""

    workspace_id: UUID
    skill_id: UUID
    document_name: str
    upload_id: str
    filename: str


def allowed_document_content_types() -> set[str]:
    """Return content types allowed for uploaded documents."""
    return parse_content_types(settings.ALLOWED_DOCUMENT_TYPES)


def skill_doc_prefix(workspace_id: UUID, skill_id: UUID, document_name: str) -> str:
    """Return the storage prefix for one skill document."""
    return validate_object_key(f"workspaces/{workspace_id}/skills/{skill_id}/docs/{document_name}")


def document_extension(filename: str, *, content_type: str | None = None) -> str:
    """Return a safe lower-case document extension."""
    suffix = PurePosixPath(safe_filename(filename)).suffix.lower()
    if suffix:
        return suffix
    if content_type:
        return _CONTENT_TYPE_EXTENSIONS.get(normalize_content_type(content_type), "")
    return ""


def original_ref(
    workspace_id: UUID,
    skill_id: UUID,
    document_name: str,
    *,
    filename: str,
) -> StorageObjectRef:
    """Build the private storage ref for an uploaded original document."""
    prefix = skill_doc_prefix(workspace_id, skill_id, document_name)
    upload_id = uuid4().hex
    filename_segment = safe_filename(filename)
    return make_storage_object_ref(
        StorageBucket.PRIVATE,
        f"{prefix}/uploads/{upload_id}/original/{filename_segment}",
    )


def markdown_ref_for_original(original: StorageObjectRef) -> StorageObjectRef:
    """Build the private storage ref for converted markdown beside an upload original."""
    parsed = parse_skill_doc_key(original.key)
    prefix = skill_doc_prefix(parsed.workspace_id, parsed.skill_id, parsed.document_name)
    return make_storage_object_ref(
        StorageBucket.PRIVATE,
        f"{prefix}/uploads/{parsed.upload_id}/converted.md",
    )


def private_ref_from_key(object_key: str) -> StorageObjectRef:
    """Return a private storage ref for a stored object key."""
    return make_storage_object_ref(StorageBucket.PRIVATE, object_key)


def parse_skill_doc_key(object_key: str) -> ParsedSkillDocumentKey:
    """Parse workspace, skill, and document name from a skill document object key."""
    parts = object_key.split("/")
    if (
        len(parts) != 10
        or parts[0] != "workspaces"
        or parts[2] != "skills"
        or parts[4] != "docs"
        or parts[6] != "uploads"
        or not parts[7]
        or parts[8] != "original"
        or not parts[9]
    ):
        raise AppValidationError("Upload token is not valid for this skill", field="upload_token")
    try:
        workspace_id = UUID(parts[1])
        skill_id = UUID(parts[3])
    except ValueError as exc:
        raise AppValidationError(
            "Upload token is not valid for this skill",
            field="upload_token",
        ) from exc
    return ParsedSkillDocumentKey(
        workspace_id=workspace_id,
        skill_id=skill_id,
        document_name=parts[5],
        upload_id=parts[7],
        filename=parts[9],
    )


async def convert_document_to_markdown(
    data: bytes,
    *,
    content_type: str,
    filename: str,
) -> str:
    """Convert uploaded document bytes into markdown, enforcing the configured cap."""
    normalized_content_type = normalize_content_type(content_type)
    if normalized_content_type in _TEXT_CONTENT_TYPES:
        markdown = data.decode("utf-8", errors="replace")
    else:
        extension = document_extension(filename, content_type=normalized_content_type)
        try:
            markdown = await asyncio.to_thread(_convert_sync, data, extension)
        except Exception as exc:
            raise SkillDocumentConversionError("Document could not be converted to markdown") from exc

    return truncate_markdown(markdown, max_bytes=settings.MAX_SKILL_DOC_MARKDOWN_BYTES)


def _convert_sync(data: bytes, extension: str) -> str:
    from markitdown import MarkItDown

    result = MarkItDown().convert_stream(io.BytesIO(data), file_extension=extension or None)
    text = getattr(result, "text_content", None)
    if text is None:
        text = getattr(result, "markdown", None)
    if not isinstance(text, str):
        raise SkillDocumentConversionError("Markdown converter returned no text content")
    return text


def truncate_markdown(markdown: str, *, max_bytes: int) -> str:
    """Truncate markdown at a UTF-8 character boundary when it exceeds max_bytes."""
    encoded = markdown.encode("utf-8")
    if len(encoded) <= max_bytes:
        return markdown

    marker_bytes = TRUNCATION_MARKER.encode("utf-8")
    allowed_content_bytes = max(0, max_bytes - len(marker_bytes))
    truncated = encoded[:allowed_content_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8") + TRUNCATION_MARKER
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return TRUNCATION_MARKER


def validate_document_upload(
    payload,
    *,
    existing_manifest: dict[str, object] | None,
) -> str:
    """Validate a skill document upload request and return normalized content type."""
    if not _matches_document_name(payload.document_name):
        raise AppValidationError(
            f"Document name must match snake_case pattern {SKILL_DOC_NAME_PATTERN}",
            field="document_name",
        )

    content_type = normalize_content_type(payload.content_type)
    if content_type not in allowed_document_content_types():
        raise AppValidationError("Unsupported skill document file type", field="content_type")
    if payload.size_bytes > settings.MAX_FILE_SIZE_DOCUMENT:
        raise AppValidationError("Skill document file is too large", field="size_bytes")

    manifest = existing_manifest or {}
    if (
        payload.document_name not in manifest
        and len(manifest) >= settings.MAX_SKILL_DOCUMENTS_PER_SKILL
    ):
        raise AppValidationError(
            "Skill document limit reached",
            field="document_name",
            details={"limit": settings.MAX_SKILL_DOCUMENTS_PER_SKILL},
        )
    return content_type


def parse_manifest_entry(
    document_name: str,
    value: object,
    *,
    skill_id: UUID,
) -> SkillDocumentEntry | None:
    """Validate one manifest entry, logging and skipping malformed legacy data."""
    try:
        return SkillDocumentEntry.model_validate(value)
    except ValidationError:
        logger.warning(
            "Skipping malformed skill document manifest entry",
            extra={"skill_id": str(skill_id), "document_name": document_name},
            exc_info=True,
        )
        return None


def entry_from_manifest(
    manifest: dict[str, object] | None,
    document_name: str,
    *,
    skill_id: UUID,
) -> SkillDocumentEntry | None:
    """Return a parsed manifest entry by name."""
    if not manifest or document_name not in manifest:
        return None
    return parse_manifest_entry(document_name, manifest[document_name], skill_id=skill_id)


def manifest_now() -> datetime:
    """Return the timestamp used for manifest entry updates."""
    return datetime.now(UTC)


async def best_effort_delete_private_object(
    object_key: str | None,
    *,
    provider: StorageProvider | None = None,
) -> None:
    """Delete a private object without failing the user operation."""
    if not object_key:
        return
    try:
        storage_provider = provider or get_storage_provider()
        await storage_provider.delete_object(private_ref_from_key(object_key))
    except Exception:
        logger.warning(
            "Failed to delete private skill document object",
            extra={"object_key": object_key},
            exc_info=True,
        )


def _matches_document_name(value: str) -> bool:
    import re

    return re.fullmatch(SKILL_DOC_NAME_PATTERN, value) is not None
