# apps/api/integrations/google_ads/tools/schemas/media.py

"""Uploading workspace images and videos, and linking YouTube videos, as Google Ads assets."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput
from services.integrations.files import FileReference

from ...references import GoogleAdsAssetReference
from .base import GoogleAdsStrictModel

MAX_MEDIA_FILES = 20
MAX_YOUTUBE_VIDEOS = 20
MAX_VIDEO_UPLOADS = 20

type GoogleAdsImageFieldType = Literal[
    "MARKETING_IMAGE",
    "SQUARE_MARKETING_IMAGE",
    "PORTRAIT_MARKETING_IMAGE",
    "LOGO",
    "LANDSCAPE_LOGO",
]


class GoogleAdsVideoDetails(GoogleAdsStrictModel):
    """The YouTube title and description for one video File; neither can change later."""

    file_id: UUID = Field(description="The video File's ID, from `files`.")
    title: str = Field(min_length=1, max_length=100, description="Without < or >.")
    description: str | None = Field(default=None, max_length=5_000, description="Without < or >.")

    @field_validator("description", mode="before")
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # The card sends an emptied description as blank text.
        return None if isinstance(value, str) and not value.strip() else value


class GoogleAdsUploadMediaRequest(GoogleAdsStrictModel):
    """Every argument of a media upload, so an edited approval is checked whole."""

    files: list[FileReference] | None = Field(default=None, max_length=MAX_MEDIA_FILES)
    youtube_videos: list[str] | None = Field(default=None, max_length=MAX_YOUTUBE_VIDEOS)
    video_details: list[GoogleAdsVideoDetails] | None = Field(
        default=None, max_length=MAX_MEDIA_FILES
    )
    video_uploads: list[str] | None = Field(default=None, max_length=MAX_VIDEO_UPLOADS)
    made_with_ai: list[UUID] | None = Field(default=None, max_length=MAX_MEDIA_FILES)


class GoogleAdsMediaUpload(GoogleAdsStrictModel):
    # `video` is a video File uploaded to YouTube, or an earlier upload finished.
    kind: Literal["image", "youtube_video", "video"]
    name: str = Field(max_length=500)
    outcome: Literal["uploaded", "linked", "processing", "failed", "unverified"]
    # True when an unclear reply was settled by finding the asset in the account.
    recovered: bool
    # Set when Google Ads has the asset.
    asset: GoogleAdsAssetReference | None
    file_id: UUID | None = None
    # The revision that was uploaded, so a later preview shows those bytes.
    revision_id: UUID | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    # The image field types the image's shape and size fit.
    fits: list[GoogleAdsImageFieldType] = Field(default_factory=list, max_length=5)
    video_id: str | None = Field(default=None, max_length=11)
    # A video upload's ID, which finishes it in a later call while Google processes it.
    upload_id: str | None = Field(default=None, max_length=32, pattern=r"^\d+$")
    duration_ms: int | None = Field(default=None, ge=0)
    # Whether Google was told the File was made or changed with AI; None when no File was sent.
    made_with_ai: bool | None = None
    # What Google's own check says about the asset; None when it says nothing.
    google_made_with_ai: bool | None = None
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class GoogleAdsMediaUploadData(GoogleAdsStrictModel):
    account_id: str
    uploads: list[GoogleAdsMediaUpload] = Field(
        max_length=MAX_MEDIA_FILES + MAX_YOUTUBE_VIDEOS + MAX_VIDEO_UPLOADS
    )


class GoogleAdsMediaUploadEntry(IntegrationFanOutEntry):
    data: GoogleAdsMediaUploadData | None = None


class GoogleAdsMediaUploadOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsMediaUploadEntry]
