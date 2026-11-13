# apps/api/integrations/meta_ads/operations/media_source.py

"""Applies Meta's media policy to workspace Files and reads their reviewed revisions."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.exceptions.general import AppValidationError, NotFoundError
from core.exceptions.integration import IntegrationValidationError
from models.files import File, FileRevision
from services.files.contract import require_matching_pair
from services.integrations.files import (
    require_pinned_file,
    resolve_workspace_file_source,
)

from ..models import MetaAdsMediaType
from ..settings import meta_ads_settings

_OPERATION = "media_source"
_MEDIA_TYPES: dict[str, MetaAdsMediaType] = {
    "image/jpeg": "image",
    "image/png": "image",
    "video/mp4": "video",
    "video/quicktime": "video",
}
_BYTES_PER_MB = 1024 * 1024
_SEAM = {"provider_key": "meta_ads", "operation": _OPERATION}


def _media_error(message: str, code: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        message, provider_key="meta_ads", operation=_OPERATION, error_code=code
    )


@dataclass(frozen=True)
class MediaSource:
    file: File
    revision: FileRevision
    media_type: MetaAdsMediaType

    def approval_details(self) -> dict[str, Any]:
        """Returns what the approval pins and shows: identity, version, type, and size."""
        return {
            "file_id": str(self.file.id),
            "revision_id": str(self.revision.id),
            "content_hash": self.revision.content_hash,
            "name": self.file.name,
            "content_type": self.revision.content_type,
            "size_bytes": self.revision.size_bytes,
            "media_type": self.media_type,
        }


async def resolve_media_source(db, *, workspace, reference) -> MediaSource:
    """Resolves a workspace File's current revision and checks it against Meta's limits."""
    try:
        file, revision = await resolve_workspace_file_source(
            db, workspace_id=workspace.id, file_id=reference.entity_id
        )
    except NotFoundError:
        raise _media_error(
            "Choose a File that is available in this workspace.", "source_unavailable"
        ) from None
    media_type = _media_type(revision)
    if media_type is None:
        raise _media_error(
            f"{file.name} isn't a JPEG or PNG image, or an MP4 or MOV video.", "unsupported_type"
        )
    if revision.size_bytes == 0:
        raise _media_error(f"{file.name} is empty.", "empty_content")
    limit = (
        meta_ads_settings.META_ADS_IMAGE_MAX_UPLOAD_BYTES
        if media_type == "image"
        else meta_ads_settings.META_ADS_VIDEO_MAX_UPLOAD_BYTES
    )
    if revision.size_bytes > limit:
        raise _media_error(
            f"{file.name} is larger than the {limit // _BYTES_PER_MB} MB limit for Meta {media_type}s.",
            "too_large",
        )
    return MediaSource(file, revision, media_type)


def _media_type(revision: FileRevision) -> MetaAdsMediaType | None:
    """Returns the media type only when the MIME type and extension agree."""
    try:
        require_matching_pair(revision.content_type, revision.extension)
    except AppValidationError:
        return None
    return _MEDIA_TYPES.get(revision.content_type)


def require_pinned(source: MediaSource, pinned: Mapping[str, Any] | None) -> None:
    """Fails when the File's current revision isn't the one the approver saw."""
    require_pinned_file(source.approval_details(), pinned, **_SEAM)
