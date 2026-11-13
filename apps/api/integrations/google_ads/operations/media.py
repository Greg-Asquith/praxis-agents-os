# apps/api/integrations/google_ads/operations/media.py

"""Applies Google's image and video upload rules to workspace Files and reads YouTube IDs."""

import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from core.exceptions.general import AppValidationError, NotFoundError
from core.exceptions.integration import IntegrationValidationError
from models.files import File, FileRevision
from services.files.contract import require_matching_pair
from services.integrations.files import resolve_workspace_file_source

_OPERATION = "upload_media"
MAX_IMAGE_BYTES = 5_120 * 1024
_FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/gif": "GIF"}
# Google publishes no limits for uploads to YouTube; this bounds one tool call's transfer.
MAX_VIDEO_BYTES = 1024 * 1024 * 1024
_VIDEO_TYPES = frozenset({"video/mp4", "video/quicktime", "video/webm"})
MAX_VIDEO_TITLE = 100
# Google takes an image for a shape when its ratio is within 1% of the shape's.
_RATIO_TOLERANCE = 0.01
_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_YOUTUBE_PATHS = {"shorts", "embed", "live", "v"}


@dataclass(frozen=True, slots=True)
class ImageShape:
    field_type: str
    ratio: float
    min_width: int
    min_height: int


# The image field types campaigns and asset groups take, with Google's minimum sizes.
IMAGE_SHAPES = (
    ImageShape("MARKETING_IMAGE", 1.91, 600, 314),
    ImageShape("SQUARE_MARKETING_IMAGE", 1.0, 300, 300),
    ImageShape("PORTRAIT_MARKETING_IMAGE", 0.8, 480, 600),
    ImageShape("LOGO", 1.0, 128, 128),
    ImageShape("LANDSCAPE_LOGO", 4.0, 512, 128),
)


def media_error(message: str, code: str) -> IntegrationValidationError:
    """Builds a refusal for a File Google won't take as an image asset."""
    return IntegrationValidationError(
        message, provider_key="google_ads", operation=_OPERATION, error_code=code
    )


@dataclass(frozen=True, slots=True)
class ImageSource:
    file: File
    revision: FileRevision

    @property
    def problem(self) -> str | None:
        """Why Google won't take the File as an image asset, or None."""
        revision = self.revision
        try:
            require_matching_pair(revision.content_type, revision.extension)
        except AppValidationError:
            return f"{self.file.name} isn't a JPEG, PNG, or GIF image."
        if revision.content_type not in _FORMATS:
            return f"{self.file.name} isn't a JPEG, PNG, or GIF image."
        if revision.size_bytes == 0:
            return f"{self.file.name} is empty."
        if revision.size_bytes > MAX_IMAGE_BYTES:
            return (
                f"This file is {-(-revision.size_bytes // 1024):,} KB. Google takes images up to "
                f"{MAX_IMAGE_BYTES // 1024:,} KB."
            )
        return None

    @property
    def asset_name(self) -> str:
        """The asset's name in Google Ads; the hash keeps two versions of one File apart."""
        return f"{self.file.name[:70]} ({self.revision.content_hash[:8]})"

    def approval_details(self) -> dict[str, Any]:
        """Returns what the approval pins and shows, before the image is read."""
        return {
            "file_id": str(self.file.id),
            "revision_id": str(self.revision.id),
            "content_hash": self.revision.content_hash,
            "name": self.file.name[:500],
            "content_type": self.revision.content_type,
            "size_bytes": self.revision.size_bytes,
            "problem": self.problem,
        }


@dataclass(frozen=True, slots=True)
class VideoSource:
    file: File
    revision: FileRevision

    @property
    def problem(self) -> str | None:
        """Why the File can't go to YouTube through Google Ads, or None."""
        revision = self.revision
        try:
            require_matching_pair(revision.content_type, revision.extension)
        except AppValidationError:
            return f"{self.file.name} isn't an MP4, MOV, or WebM video."
        if revision.content_type not in _VIDEO_TYPES:
            return f"{self.file.name} isn't an MP4, MOV, or WebM video."
        if revision.size_bytes == 0:
            return f"{self.file.name} is empty."
        if revision.size_bytes > MAX_VIDEO_BYTES:
            return f"{self.file.name} is larger than the 1 GB limit for video uploads."
        return None

    @property
    def default_title(self) -> str:
        """The File's name without `<` or `>`, which YouTube titles can't contain."""
        name = " ".join(self.file.name.replace("<", " ").replace(">", " ").split())
        return name[:MAX_VIDEO_TITLE] or "Video"

    @property
    def duration_ms(self) -> int | None:
        """The video's length when the media renderer has measured it."""
        metadata = self.revision.media_metadata
        duration = metadata.get("duration_ms") if isinstance(metadata, dict) else None
        if isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0:
            return duration
        return None

    def approval_details(self) -> dict[str, Any]:
        """Returns what the approval pins and shows; the video is never read before approval."""
        return {
            "file_id": str(self.file.id),
            "revision_id": str(self.revision.id),
            "content_hash": self.revision.content_hash,
            "name": self.file.name[:500],
            "content_type": self.revision.content_type,
            "size_bytes": self.revision.size_bytes,
            "problem": self.problem,
        }


type MediaSource = ImageSource | VideoSource


async def resolve_media_source(db, *, workspace_id: UUID, file_id: UUID) -> MediaSource:
    """Resolves a workspace File's current revision as a video when it is one, else an image.

    `problem` says whether Google takes it.
    """
    try:
        file, revision = await resolve_workspace_file_source(
            db, workspace_id=workspace_id, file_id=file_id
        )
    except NotFoundError:
        raise media_error(
            "Choose a File that is available in this workspace.", "source_unavailable"
        ) from None
    if revision.content_type.startswith("video/"):
        return VideoSource(file, revision)
    return ImageSource(file, revision)


def video_text_problem(value: str, *, label: str) -> str | None:
    """Says why a YouTube title or description can't be used, or None."""
    if not value.strip():
        return f"Enter a {label}."
    if "<" in value or ">" in value:
        return f"The {label} can't contain < or >."
    return None


def image_size(data: bytes, content_type: str) -> tuple[int, int] | None:
    """Reads the width and height from the image header; None when it isn't that format."""
    expected = _FORMATS.get(content_type)
    if expected is None:
        return None
    try:
        with Image.open(BytesIO(data), formats=(expected,)) as image:
            width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def image_fits(width: int, height: int) -> tuple[list[str], list[str]]:
    """Returns the field types an image fits, and those with its shape it's too small for."""
    fits: list[str] = []
    too_small: list[str] = []
    for shape in IMAGE_SHAPES:
        if abs(width / height - shape.ratio) > shape.ratio * _RATIO_TOLERANCE:
            continue
        if width >= shape.min_width and height >= shape.min_height:
            fits.append(shape.field_type)
        else:
            too_small.append(shape.field_type)
    return fits, too_small


def youtube_video_id(value: str) -> str | None:
    """Returns the video ID in a YouTube link or bare ID, or None when there isn't one."""
    text = value.strip()
    if _YOUTUBE_ID.fullmatch(text):
        return text
    try:
        url = urlsplit(text if "://" in text else f"https://{text}")
    except ValueError:
        return None
    host = (url.hostname or "").lower()
    parts = [part for part in url.path.split("/") if part]
    candidate = ""
    if host == "youtu.be" and parts:
        candidate = parts[0]
    elif host in _YOUTUBE_HOSTS and url.path == "/watch":
        candidate = (parse_qs(url.query).get("v") or [""])[0]
    elif host in _YOUTUBE_HOSTS and len(parts) >= 2 and parts[0] in _YOUTUBE_PATHS:
        candidate = parts[1]
    return candidate if _YOUTUBE_ID.fullmatch(candidate) else None
