# apps/api/integrations/meta_ads/tools/schemas/media.py

"""Results of uploading workspace Files to an ad account's media library."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsMediaType, MetaAdsStrictModel
from ...references import MetaAdsMediaReference


class MetaAdsMediaUpload(MetaAdsStrictModel):
    file_id: UUID
    # The revision that was uploaded, so a later preview shows those bytes.
    revision_id: UUID
    name: str = Field(max_length=500)
    media_type: MetaAdsMediaType
    outcome: Literal["uploaded", "processing", "failed", "unverified"]
    # True when an unclear reply was settled by finding the upload in the media library.
    recovered: bool
    # Set when Meta has the media; pass it to ad creation as is.
    media: MetaAdsMediaReference | None
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsMediaUploadData(MetaAdsStrictModel):
    account_id: MetaAdsId
    uploads: list[MetaAdsMediaUpload] = Field(max_length=20)


class MetaAdsMediaUploadEntry(IntegrationFanOutEntry):
    data: MetaAdsMediaUploadData | None = None


class MetaAdsMediaUploadOutput(IntegrationFanOutOutput):
    results: list[MetaAdsMediaUploadEntry]
