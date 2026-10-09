# apps/api/integrations/meta_ads/preview.py

"""Meta Ads media pictures for the generic integration preview route."""

import re
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import IntegrationConnection
from services.integrations.plugin import (
    IntegrationPreviewDefinition,
    IntegrationPreviewPayload,
    IntegrationPreviewRequest,
)

from .tools.utils.client import meta_ads_client_for_connection

PREVIEW_OPERATION = "preview_meta_ads_media"
_REF = re.compile(
    r"image_(?P<image>[A-Za-z0-9]{1,64})|video_(?P<video>[0-9]{1,128})|page_(?P<page>[0-9]{1,128})"
)


async def fetch_media_preview(
    db: AsyncSession, connection: IntegrationConnection, request: IntegrationPreviewRequest
) -> IntegrationPreviewPayload:
    """Returns a library image, video thumbnail, or Page picture for the conversation's ad account."""
    # Resolve at call time so tests can replace the operation without rebuilding the plugin.
    from .operations.preview_media import MetaAdsPreviewType, preview_media

    account_id = request.scope_id
    if account_id is None or not account_id.isdigit():
        raise IntegrationValidationError(
            "A Meta Ads media preview needs an ad account from the conversation.",
            provider_key="meta_ads",
            operation=PREVIEW_OPERATION,
        )
    match = _REF.fullmatch(request.ref)
    if match is None:
        raise IntegrationValidationError(
            "The preview reference is invalid for this provider",
            provider_key="meta_ads",
            operation=PREVIEW_OPERATION,
        )
    client = meta_ads_client_for_connection(
        db, actor=request.actor, workspace=request.workspace, connection_id=connection.id
    )
    content, width, height = await preview_media(
        client,
        account_id=account_id,
        media_type=cast(MetaAdsPreviewType, match.lastgroup),
        media_id=match[match.lastgroup or ""],
    )
    return IntegrationPreviewPayload(
        content_type="image", content=content, meta={"width": width, "height": height}
    )


META_ADS_MEDIA_PREVIEW = IntegrationPreviewDefinition(
    kind="meta_ads_media",
    operation=PREVIEW_OPERATION,
    fetch=fetch_media_preview,
    ref_pattern=_REF,
)
