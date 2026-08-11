# apps/api/services/files/write_generated_image.py

"""Persist one provider-generated image as a governed workspace file."""

import logging
import re
import struct
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent import Agent
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import safe_record_operation_audit_event
from services.files.contract import contract_for_content_type, max_size_bytes
from services.files.create_file_with_revision import create_file_with_revision
from services.files.get_files_usage import get_files_usage
from services.files.revision_actor import FileRevisionActor

logger = logging.getLogger(__name__)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8"
_WEBP_RIFF_SIGNATURE = b"RIFF"
_WEBP_SIGNATURE = b"WEBP"
_SAFE_NAME_TOKEN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class GeneratedImageWriteResult:
    """Stored image identifiers and metadata returned to the runtime tool."""

    file_id: UUID
    revision_id: UUID
    name: str
    size_bytes: int
    width: int
    height: int
    content_type: str


async def write_generated_image(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    prompt: str,
    content: bytes,
    media_type: str,
) -> GeneratedImageWriteResult:
    """Validate and store a supported generated image with agent provenance and audit."""
    if len(content) > settings.MAX_FILE_SIZE_IMAGE:
        raise AppValidationError(
            "Generated image is too large",
            field="content",
            details={
                "content_bytes": len(content),
                "max_bytes": settings.MAX_FILE_SIZE_IMAGE,
            },
        )
    detected_type, extension, width, height = generated_image_metadata(content)
    if media_type.split(";", 1)[0].strip().lower() != detected_type:
        logger.warning(
            "Generated image media type did not match its bytes",
            extra={"declared_media_type": media_type, "detected_media_type": detected_type},
        )
    entry = contract_for_content_type(detected_type)
    if len(content) > max_size_bytes(entry):
        raise AppValidationError(
            "Generated image is too large",
            field="content",
            details={"content_bytes": len(content), "max_bytes": max_size_bytes(entry)},
        )
    usage = await get_files_usage(db, workspace=workspace)
    if usage.used_bytes + len(content) > usage.soft_limit_bytes:
        logger.warning(
            "Generated image would exceed the workspace file soft limit",
            extra={
                "workspace_id": str(workspace.id),
                "used_bytes": usage.used_bytes,
                "generated_bytes": len(content),
                "soft_limit_bytes": usage.soft_limit_bytes,
            },
        )

    name = generated_image_name(prompt, extension=extension)
    stored = await create_file_with_revision(
        db,
        workspace=workspace,
        name=name,
        content=content,
        content_type=entry.content_type,
        extension=extension,
        actor=FileRevisionActor(agent_id=agent.id),
    )
    await safe_record_operation_audit_event(
        db,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.FILE,
        resource_id=stored.file.id,
        actor_type=AuditActorType.AGENT,
        actor_id=agent.id,
        actor_display=agent.name,
        details={
            "filename": stored.file.name,
            "size_bytes": stored.bytes_written,
            "revision_kind": stored.revision.revision_kind,
            "content_hash": stored.revision.content_hash,
            "source": "native_image_generation",
            "width": width,
            "height": height,
        },
    )
    return GeneratedImageWriteResult(
        file_id=stored.file.id,
        revision_id=stored.revision.id,
        name=stored.file.name,
        size_bytes=stored.bytes_written,
        width=width,
        height=height,
        content_type=entry.content_type,
    )


def generated_image_metadata(content: bytes) -> tuple[str, str, int, int]:
    """Identify a supported provider image and return type, extension, and dimensions."""
    if len(content) >= 24 and content[:8] == _PNG_SIGNATURE and content[12:16] == b"IHDR":
        width, height = struct.unpack(">II", content[16:24])
        return _valid_image_metadata("image/png", ".png", width, height)
    if (
        len(content) >= 30
        and content[:4] == _WEBP_RIFF_SIGNATURE
        and content[8:12] == _WEBP_SIGNATURE
    ):
        width, height = webp_dimensions(content)
        return _valid_image_metadata("image/webp", ".webp", width, height)
    if len(content) >= 4 and content[:2] == _JPEG_SIGNATURE:
        width, height = jpeg_dimensions(content)
        return _valid_image_metadata("image/jpeg", ".jpg", width, height)
    raise AppValidationError(
        "Image provider returned an unsupported or invalid image format",
        field="content",
    )


def _valid_image_metadata(
    content_type: str,
    extension: str,
    width: int,
    height: int,
) -> tuple[str, str, int, int]:
    if width < 1 or height < 1:
        raise AppValidationError(
            "Image provider returned invalid image dimensions", field="content"
        )
    return content_type, extension, width, height


def webp_dimensions(content: bytes) -> tuple[int, int]:
    """Read dimensions from the three WebP bitstream header variants."""
    chunk_type = content[12:16]
    if chunk_type == b"VP8X" and len(content) >= 30:
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
        return width, height
    if chunk_type == b"VP8 " and len(content) >= 30 and content[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(content[26:28], "little") & 0x3FFF
        height = int.from_bytes(content[28:30], "little") & 0x3FFF
        return width, height
    if chunk_type == b"VP8L" and len(content) >= 25 and content[20] == 0x2F:
        bits = int.from_bytes(content[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise AppValidationError("Image provider returned an invalid WebP image", field="content")


def jpeg_dimensions(content: bytes) -> tuple[int, int]:
    """Read dimensions from a JPEG start-of-frame segment."""
    offset = 2
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(content):
            break
        segment_length = int.from_bytes(content[offset : offset + 2], "big")
        if segment_length < 2 or offset + segment_length > len(content):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                break
            height = int.from_bytes(content[offset + 3 : offset + 5], "big")
            width = int.from_bytes(content[offset + 5 : offset + 7], "big")
            return width, height
        offset += segment_length
    raise AppValidationError("Image provider returned an invalid JPEG image", field="content")


def generated_image_name(prompt: str, *, extension: str = ".png") -> str:
    """Build a readable, collision-resistant image name from the approved prompt."""
    stem = _SAFE_NAME_TOKEN.sub("-", prompt.strip().lower()).strip("-")[:48].rstrip("-")
    if not stem:
        stem = "generated-image"
    return f"{stem}-{uuid4().hex[:8]}{extension}"
