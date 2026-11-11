# apps/api/integrations/google_ads/tools/schemas/media.py

"""Results of uploading workspace images and linking YouTube videos as Google Ads assets."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsAssetReference
from .base import GoogleAdsStrictModel

MAX_MEDIA_FILES = 20
MAX_YOUTUBE_VIDEOS = 20

type GoogleAdsImageFieldType = Literal[
    "MARKETING_IMAGE",
    "SQUARE_MARKETING_IMAGE",
    "PORTRAIT_MARKETING_IMAGE",
    "LOGO",
    "LANDSCAPE_LOGO",
]


class GoogleAdsMediaUpload(GoogleAdsStrictModel):
    kind: Literal["image", "youtube_video"]
    name: str = Field(max_length=500)
    outcome: Literal["uploaded", "linked", "failed", "unverified"]
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
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class GoogleAdsMediaUploadData(GoogleAdsStrictModel):
    account_id: str
    uploads: list[GoogleAdsMediaUpload] = Field(max_length=MAX_MEDIA_FILES + MAX_YOUTUBE_VIDEOS)


class GoogleAdsMediaUploadEntry(IntegrationFanOutEntry):
    data: GoogleAdsMediaUploadData | None = None


class GoogleAdsMediaUploadOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsMediaUploadEntry]
